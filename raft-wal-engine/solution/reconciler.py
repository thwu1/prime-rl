#!/usr/bin/env python3
"""
Raft WAL multi-node reconciler.

Reads RLOG/RSNP binary format as defined by /app/gowal/wal.go.
Cross-references a multi-node Raft cluster's WAL data to determine
the committed log using majority-replication and term-based conflict
resolution.

Binary format (from wal.go):
  Segment header: magic('RLOG',4) + version(uint16 LE,2) +
                  first_index(uint64 LE,8) + entry_count(uint32 LE,4) = 18 bytes
  Entry: index(8) + term(8) + timestamp(8) + payload_len(4) +
         payload(N) + crc32(4)
         CRC-32 IEEE covers index through payload.
  Snapshot: magic('RSNP',4) + version(2) + last_index(8) + last_term(8) +
            state_len(4) + state_data(N) + crc32(4)
            CRC-32 IEEE covers everything before the trailing CRC.
"""

import glob
import json
import os
import struct
import sys
import zlib

SEGMENT_MAGIC = b'RLOG'
SNAPSHOT_MAGIC = b'RSNP'
SEG_HDR = 18


def _parse_segment(path):
    """Parse segment file. Returns (clean_entries, crc_errors).
    clean_entries: list of {index, term, payload}
    crc_errors: list of {index, term} for entries with CRC mismatch
    """
    with open(path, 'rb') as f:
        raw = f.read()
    if len(raw) < SEG_HDR or raw[:4] != SEGMENT_MAGIC:
        return [], []

    count = struct.unpack_from('<I', raw, 14)[0]
    clean, crc_err = [], []
    off = SEG_HDR

    for i in range(count):
        if off + 28 > len(raw):
            break
        idx = struct.unpack_from('<Q', raw, off)[0]
        term = struct.unpack_from('<Q', raw, off + 8)[0]
        plen = struct.unpack_from('<I', raw, off + 24)[0]
        end = off + 28 + plen + 4
        if end > len(raw):
            break
        stored = struct.unpack_from('<I', raw, off + 28 + plen)[0]
        computed = zlib.crc32(raw[off:off + 28 + plen]) & 0xFFFFFFFF
        if stored != computed:
            crc_err.append({'index': idx, 'term': term})
        else:
            payload = raw[off + 28:off + 28 + plen].decode('utf-8')
            clean.append({'index': idx, 'term': term, 'payload': payload})
        off = end

    return clean, crc_err


def _parse_snapshot(path):
    """Parse snapshot. Returns ({last_index, last_term, state}, valid)."""
    with open(path, 'rb') as f:
        raw = f.read()
    if len(raw) < 30 or raw[:4] != SNAPSHOT_MAGIC:
        return None, False
    stored = struct.unpack_from('<I', raw, len(raw) - 4)[0]
    computed = zlib.crc32(raw[:len(raw) - 4]) & 0xFFFFFFFF
    if stored != computed:
        return None, False
    li = struct.unpack_from('<Q', raw, 6)[0]
    lt = struct.unpack_from('<Q', raw, 14)[0]
    slen = struct.unpack_from('<I', raw, 22)[0]
    state = json.loads(raw[26:26 + slen])
    return {'last_index': li, 'last_term': lt, 'state': state}, True


def _apply(state, cmd):
    parts = cmd.split(' ', 2)
    if parts[0] == 'SET' and len(parts) >= 3:
        state[parts[1]] = parts[2]
    elif parts[0] == 'DEL' and len(parts) >= 2:
        state.pop(parts[1], None)


def reconcile(cluster_dir):
    """Reconcile a multi-node Raft WAL cluster.
    Returns (committed_state: dict, report: dict).
    """
    node_dirs = sorted(
        d for d in glob.glob(os.path.join(cluster_dir, 'node_*'))
        if os.path.isdir(d)
    )
    majority = len(node_dirs) // 2 + 1

    # Phase 1: parse every node
    node_clean = {}
    node_crc_err = {}
    node_snap = {}

    for nd in node_dirs:
        name = os.path.basename(nd)
        all_clean, all_err = [], []
        for sf in sorted(glob.glob(os.path.join(nd, 'segment_*.wal'))):
            c, e = _parse_segment(sf)
            all_clean.extend(c)
            all_err.extend(e)
        node_clean[name] = all_clean
        node_crc_err[name] = all_err
        snaps = sorted(glob.glob(os.path.join(nd, 'snapshot_*.snap')))
        node_snap[name] = _parse_snapshot(snaps[-1]) if snaps else (None, False)

    node_names = sorted(node_clean.keys())

    # Phase 2: build presence and clean-payload maps
    # presence[idx][term] = set of node names (clean OR crc-failed)
    # clean_map[idx][term] = [(node, payload)]
    presence = {}
    clean_map = {}

    for name in node_names:
        for e in node_clean[name]:
            presence.setdefault(e['index'], {}).setdefault(e['term'], set()).add(name)
            clean_map.setdefault(e['index'], {}).setdefault(e['term'], []).append(
                (name, e['payload']))
        for e in node_crc_err[name]:
            presence.setdefault(e['index'], {}).setdefault(e['term'], set()).add(name)

    # Phase 3: determine committed entries via majority voting
    committed_log = {}   # idx -> (term, payload)
    stale_entries = {}   # node -> [idx]

    for idx in sorted(presence.keys()):
        best_term = None
        for term in sorted(presence[idx].keys(), reverse=True):
            if len(presence[idx][term]) >= majority:
                best_term = term
                break
        if best_term is None:
            for term, nodes_set in presence[idx].items():
                for n in nodes_set:
                    stale_entries.setdefault(n, []).append(idx)
            continue

        payload = None
        if idx in clean_map and best_term in clean_map[idx]:
            payload = clean_map[idx][best_term][0][1]
        committed_log[idx] = (best_term, payload)

        for term, nodes_set in presence[idx].items():
            if term != best_term:
                for n in nodes_set:
                    stale_entries.setdefault(n, []).append(idx)

    # Phase 4: identify cross-referenced recoveries
    cross_ref = set()
    corrupted_entries = {}
    for name in node_names:
        ce = sorted(e['index'] for e in node_crc_err[name])
        if ce:
            corrupted_entries[name] = ce
        for e in node_crc_err[name]:
            idx = e['index']
            if idx in committed_log and committed_log[idx][1] is not None:
                cross_ref.add(idx)

    # Phase 5: determine base state from best valid snapshot
    best_snap = None
    best_snap_idx = 0
    for name in node_names:
        snap_data, valid = node_snap[name]
        if valid and snap_data and snap_data['last_index'] > best_snap_idx:
            best_snap = snap_data
            best_snap_idx = snap_data['last_index']

    state = dict(best_snap['state']) if best_snap else {}

    # Phase 6: replay committed entries after snapshot
    for idx in sorted(committed_log.keys()):
        if idx > best_snap_idx:
            _, payload = committed_log[idx]
            if payload is not None:
                _apply(state, payload)

    # Phase 7: build report
    commit_index = max(committed_log.keys()) if committed_log else 0
    committed_count = best_snap_idx + sum(
        1 for idx in committed_log if idx > best_snap_idx)

    for k in stale_entries:
        stale_entries[k] = sorted(set(stale_entries[k]))

    report = {
        'commit_index': commit_index,
        'committed_entry_count': committed_count,
        'stale_entries': {k: v for k, v in stale_entries.items() if v},
        'corrupted_entries': corrupted_entries,
        'cross_referenced_recoveries': sorted(cross_ref),
    }

    return state, report


if __name__ == '__main__':
    cdir = sys.argv[1] if len(sys.argv) > 1 else '/app/cluster'
    st, rp = reconcile(cdir)
    with open('/app/committed_state.json', 'w') as f:
        json.dump(st, f, sort_keys=True, indent=2)
    with open('/app/reconciliation.json', 'w') as f:
        json.dump(rp, f, indent=2)
    print(f"State: {len(st)} keys, commit_index: {rp['commit_index']}")
    print(f"Stale: {rp['stale_entries']}")
    print(f"Corrupted: {rp['corrupted_entries']}")
    print(f"Cross-ref: {rp['cross_referenced_recoveries']}")
