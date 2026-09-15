"""Working implementation of TransitionEngine.

Copied to /app/transition_engine.py by solve.sh.

"""

import hashlib
from galois import gf, gf_matrix_inv
from reed_solomon import encode, decode, make_encoding_matrix
from cluster import Cluster, NodeFailureError, ShardNotFoundError


class TransitionEngine:

    def __init__(self, cluster: Cluster):
        self.cluster = cluster

    # -- helpers --------------------------------------------------------

    def _base_node(self, file_id: str) -> int:
        h = int(hashlib.sha256(file_id.encode()).hexdigest()[:8], 16)
        return h % self.cluster.num_nodes

    def _pick_nodes(self, count, exclude=None):
        """Return *count* alive node-ids not in *exclude*."""
        exclude = set(exclude or [])
        out = []
        for n in self.cluster.nodes:
            if n.node_id not in exclude and n.is_alive:
                out.append(n.node_id)
                if len(out) == count:
                    break
        if len(out) < count:
            raise ValueError("not enough alive nodes")
        return out

    # -- 1. encode_file ------------------------------------------------

    def encode_file(self, file_id, data, k, m):
        shards = encode(data, k, m)
        base = self._base_node(file_id)
        n = self.cluster.num_nodes
        locs = {}
        for i, s in enumerate(shards):
            nid = (base + i) % n
            self.cluster.get_node(nid).put_shard(file_id, i, s)
            locs[str(i)] = nid
        meta = {
            'k': k, 'm': m,
            'original_size': len(data),
            'shard_locations': locs,
            'checksum': hashlib.sha256(data).hexdigest(),
        }
        self.cluster.register_file(file_id, meta)
        return meta

    # -- 2. plan_transition --------------------------------------------

    def plan_transition(self, file_id, target_k, target_m):
        meta = self.cluster.get_file_metadata(file_id)
        if meta is None:
            raise FileNotFoundError(file_id)
        ck, cm = meta['k'], meta['m']
        plan = {
            'file_id': file_id,
            'current_scheme': (ck, cm),
            'target_scheme': (target_k, target_m),
            'keep': [], 'delete': [], 'create': [],
            'data_movement_bytes': 0,
        }

        if ck == target_k:
            # --- same-k: keep data, recompute parity ------------------
            for i in range(ck):
                plan['keep'].append((i, meta['shard_locations'][str(i)]))
            for i in range(ck, ck + cm):
                plan['delete'].append((i, meta['shard_locations'][str(i)]))

            # read data shards
            dshard = []
            for i in range(ck):
                nid = meta['shard_locations'][str(i)]
                dshard.append(self.cluster.get_node(nid).get_shard(file_id, i))
            ss = len(dshard[0])

            # compute new parity with target encoding matrix
            enc = make_encoding_matrix(target_k, target_m)
            prows = enc[target_k:]
            new_par = []
            for pi in range(target_m):
                buf = bytearray(ss)
                for pos in range(ss):
                    v = 0
                    for j in range(target_k):
                        v ^= gf.mul(prows[pi][j], dshard[j][pos])
                    buf[pos] = v
                new_par.append(bytes(buf))

            # choose nodes for new parity (reuse old parity nodes first)
            data_nids = {meta['shard_locations'][str(i)] for i in range(ck)}
            old_par_nids = [meta['shard_locations'][str(i)]
                           for i in range(ck, ck + cm)]
            # candidates: old-parity nodes then any unused alive node
            used = set(data_nids)
            cands = []
            for nid in old_par_nids:
                if nid not in used:
                    cands.append(nid)
                    used.add(nid)
            for nid in range(self.cluster.num_nodes):
                if nid not in used:
                    cands.append(nid)
                    used.add(nid)
                if len(cands) >= target_m:
                    break

            for pi in range(target_m):
                sidx = target_k + pi
                plan['create'].append((sidx, cands[pi], new_par[pi]))
        else:
            # --- different-k: full re-encode --------------------------
            dshard = []
            for i in range(ck):
                nid = meta['shard_locations'][str(i)]
                dshard.append(self.cluster.get_node(nid).get_shard(file_id, i))
            orig = b''.join(dshard)[:meta['original_size']]

            new_shards = encode(orig, target_k, target_m)

            for i in range(ck + cm):
                plan['delete'].append((i, meta['shard_locations'][str(i)]))

            base = self._base_node(file_id)
            n = self.cluster.num_nodes
            for i, s in enumerate(new_shards):
                plan['create'].append((i, (base + i) % n, s))

        plan['data_movement_bytes'] = sum(len(d) for _, _, d in plan['create'])
        return plan

    # -- 3. execute_transition -----------------------------------------

    def execute_transition(self, plan):
        fid = plan['file_id']
        tk, tm = plan['target_scheme']
        meta = self.cluster.get_file_metadata(fid)

        final = {}
        for idx, nid in plan['keep']:
            final[idx] = nid
        for idx, nid, _ in plan['create']:
            final[idx] = nid

        # 1. create new shards
        for idx, nid, data in plan['create']:
            self.cluster.get_node(nid).put_shard(fid, idx, data)

        # 2. delete superseded shards
        for idx, nid in plan['delete']:
            if final.get(idx) != nid:
                self.cluster.get_node(nid).delete_shard(fid, idx)

        new_meta = {
            'k': tk, 'm': tm,
            'original_size': meta['original_size'],
            'shard_locations': {str(i): n for i, n in final.items()},
            'checksum': meta['checksum'],
        }
        self.cluster.register_file(fid, new_meta)
        return new_meta

    # -- 4. reconstruct_read -------------------------------------------

    def reconstruct_read(self, file_id, failed_nodes=None):
        meta = self.cluster.get_file_metadata(file_id)
        if meta is None:
            raise FileNotFoundError(file_id)
        k, m = meta['k'], meta['m']

        if failed_nodes is None:
            bad = {n.node_id for n in self.cluster.nodes if not n.is_alive}
        else:
            bad = set(failed_nodes)

        avail_idx, avail_data = [], []
        for i in range(k + m):
            nid = meta['shard_locations'][str(i)]
            if nid in bad:
                continue
            try:
                avail_data.append(
                    self.cluster.get_node(nid).get_shard(file_id, i))
                avail_idx.append(i)
            except (NodeFailureError, ShardNotFoundError):
                continue

        if len(avail_data) < k:
            raise ValueError(
                f"need {k} shards, only {len(avail_data)} available")

        dshard = decode(avail_data[:k], k, m, avail_idx[:k])
        result = b''.join(dshard)[:meta['original_size']]

        if hashlib.sha256(result).hexdigest() != meta['checksum']:
            raise ValueError("checksum mismatch")
        return result

    # -- 5. repair -----------------------------------------------------

    def repair(self, file_id, failed_nodes):
        meta = self.cluster.get_file_metadata(file_id)
        if meta is None:
            raise FileNotFoundError(file_id)
        k, m = meta['k'], meta['m']
        bad = set(failed_nodes)

        lost = []
        for i in range(k + m):
            if meta['shard_locations'][str(i)] in bad:
                lost.append(i)
        if not lost:
            return meta

        avail_idx, avail_data = [], []
        for i in range(k + m):
            nid = meta['shard_locations'][str(i)]
            if nid not in bad:
                avail_data.append(
                    self.cluster.get_node(nid).get_shard(file_id, i))
                avail_idx.append(i)

        if len(avail_data) < k:
            raise ValueError(
                f"cannot repair: need {k} shards, have {len(avail_data)}")

        dshard = decode(avail_data[:k], k, m, avail_idx[:k])
        orig = b''.join(dshard)[:meta['original_size']]
        all_shards = encode(orig, k, m)

        used = set()
        for i in range(k + m):
            nid = meta['shard_locations'][str(i)]
            if nid not in bad:
                used.add(nid)

        new_locs = dict(meta['shard_locations'])
        free = [n for n in range(self.cluster.num_nodes)
                if n not in bad and n not in used]
        fi = 0
        for sidx in lost:
            if fi >= len(free):
                raise ValueError("not enough alive nodes for repair")
            nid = free[fi]; fi += 1
            self.cluster.get_node(nid).put_shard(file_id, sidx,
                                                 all_shards[sidx])
            new_locs[str(sidx)] = nid
            used.add(nid)

        new_meta = {
            'k': k, 'm': m,
            'original_size': meta['original_size'],
            'shard_locations': new_locs,
            'checksum': meta['checksum'],
        }
        self.cluster.register_file(file_id, new_meta)
        return new_meta
