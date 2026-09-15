#!/usr/bin/env python3
"""
Floorplan optimizer: partition-guided sequence packing with simulated annealing.
Uses gpmetis for graph partitioning, outputs Bookshelf .pl format and gnuplot visualization.

"""

import math
import os
import random
import subprocess
import time


class FloorplanOptimizer:
    def __init__(self):
        os.makedirs("/app/output", exist_ok=True)

    def _write_and_run_metis(self, instance):
        """Convert block connectivity to METIS weighted-graph format and run gpmetis."""
        name = instance["name"]
        n = instance["block_count"]
        b2b_edges = instance["b2b_edges"]

        # Build adjacency lists with integer weights (METIS requires integers)
        adj = [[] for _ in range(n)]
        edge_count = 0
        for src, dst, w in b2b_edges:
            iw = max(1, int(round(w * 100)))
            adj[src].append((dst + 1, iw))  # METIS uses 1-indexed vertices
            adj[dst].append((src + 1, iw))
            edge_count += 1

        metis_path = f"/app/output/{name}.metis"
        with open(metis_path, "w") as f:
            f.write(f"{n} {edge_count} 1\n")  # fmt=1 for edge weights
            for i in range(n):
                parts = []
                for nb, w in adj[i]:
                    parts.append(f"{nb} {w}")
                f.write(" ".join(parts) + "\n")

        # Choose partition count based on design size
        nparts = max(2, n // 10)
        partitions = [i % nparts for i in range(n)]

        try:
            subprocess.run(
                ["gpmetis", metis_path, str(nparts)],
                capture_output=True, text=True, timeout=30, check=False
            )
            part_file = f"{metis_path}.part.{nparts}"
            if os.path.exists(part_file):
                with open(part_file) as f:
                    for i, line in enumerate(f):
                        line = line.strip()
                        if i < n and line:
                            partitions[i] = int(line)
        except Exception:
            # Write fallback partition file if gpmetis failed
            part_file = f"{metis_path}.part.{nparts}"
            with open(part_file, "w") as f:
                for i in range(n):
                    f.write(f"{i % nparts}\n")

        return partitions, nparts

    def _write_bookshelf_pl(self, instance, placement):
        """Write final placement in Bookshelf .pl format."""
        name = instance["name"]
        n = instance["block_count"]
        block_types = instance["block_types"]

        pl_path = f"/app/output/{name}.pl"
        with open(pl_path, "w") as f:
            f.write("UCLA pl 1.0\n")
            for i in range(n):
                x, y, w, h = placement[i]
                fixed_str = " /FIXED" if block_types[i] == 2 else ""
                f.write(f"block_{i} {x:.4f} {y:.4f} : N{fixed_str}\n")

    def _write_gnuplot_viz(self, instance, placement, partitions, nparts):
        """Generate gnuplot script and render placement visualization to PNG."""
        name = instance["name"]
        n = instance["block_count"]

        colors = ["#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00",
                  "#a65628", "#f781bf", "#999999", "#66c2a5", "#ffd92f"]

        gp_path = f"/app/output/{name}.gnuplot"
        png_path = f"/app/output/{name}.png"

        max_x = max(p[0] + p[2] for p in placement) * 1.05
        max_y = max(p[1] + p[3] for p in placement) * 1.05

        with open(gp_path, "w") as f:
            f.write("set terminal png size 1024,768\n")
            f.write(f"set output '{png_path}'\n")
            f.write(f"set title 'Floorplan: {name} ({n} blocks, {nparts} partitions)'\n")
            f.write("set xlabel 'X'\n")
            f.write("set ylabel 'Y'\n")
            f.write("unset key\n")

            for i in range(n):
                x, y, w, h = placement[i]
                color = colors[partitions[i] % len(colors)]
                f.write(
                    f"set object {i + 1} rect from {x:.4f},{y:.4f} "
                    f"to {x + w:.4f},{y + h:.4f} "
                    f"fc rgb '{color}' fs transparent solid 0.4 "
                    f"border lc rgb 'black'\n"
                )

            f.write(f"plot [0:{max_x:.1f}] [0:{max_y:.1f}] 1/0 notitle\n")

        try:
            subprocess.run(
                ["gnuplot", gp_path],
                capture_output=True, timeout=15, check=False
            )
        except Exception:
            pass

    def solve(self, instance):
        n = instance["block_count"]
        area_targets = instance["area_targets"]
        block_types = instance["block_types"]
        target_dims = instance["target_dims"]
        target_pos = instance["target_pos"]
        b2b_edges = instance["b2b_edges"]
        p2b_edges = instance["p2b_edges"]
        pin_positions = instance["pin_positions"]
        mib_groups = instance.get("mib_groups", [])
        cluster_groups = instance.get("cluster_groups", [])
        boundary_constraints = instance.get("boundary_constraints", [0] * n)

        rng = random.Random(42)

        # ---- METIS Partitioning ----
        partitions, nparts = self._write_and_run_metis(instance)

        # ---- Initialize dimensions ----
        widths = [0.0] * n
        heights = [0.0] * n
        for i in range(n):
            if block_types[i] >= 1:
                widths[i] = target_dims[i][0]
                heights[i] = target_dims[i][1]
            else:
                w = math.sqrt(area_targets[i])
                widths[i] = w
                heights[i] = area_targets[i] / w

        for group in mib_groups:
            avg = sum(area_targets[i] for i in group) / len(group)
            w = math.sqrt(avg)
            h = avg / w
            for idx in group:
                if block_types[idx] == 0:
                    widths[idx] = w
                    heights[idx] = h

        preplaced_set = set(i for i in range(n) if block_types[i] == 2)
        preplaced_list = sorted(preplaced_set)
        movable = [i for i in range(n) if block_types[i] != 2]
        soft_blocks = [i for i in movable if block_types[i] == 0]

        if not movable:
            placement = [[target_pos[i][0], target_pos[i][1],
                          target_dims[i][0], target_dims[i][1]] for i in range(n)]
            self._write_bookshelf_pl(instance, placement)
            self._write_gnuplot_viz(instance, placement, partitions, nparts)
            return placement

        # ---- Build adjacency ----
        adj = [[] for _ in range(n)]
        for src, dst, w in b2b_edges:
            adj[src].append((dst, w))
            adj[dst].append((src, w))

        movable_set = set(movable)
        conn_weight = [sum(w for _, w in adj[i]) for i in range(n)]

        # ---- Generate initial orderings ----
        def make_bfs_order(start_block):
            vis = set()
            order = []
            q = [start_block]
            vis.add(start_block)
            while q:
                nd = q.pop(0)
                if nd in movable_set:
                    order.append(nd)
                for nb, _ in sorted(adj[nd], key=lambda x: -x[1]):
                    if nb not in vis:
                        vis.add(nb)
                        q.append(nb)
            for i in movable:
                if i not in vis:
                    order.append(i)
                    vis.add(i)
            return order

        def make_partition_order():
            """Order blocks by METIS partition, then by connectivity within each partition."""
            groups = [[] for _ in range(nparts)]
            for idx in movable:
                groups[partitions[idx]].append(idx)
            for g in groups:
                g.sort(key=lambda i: -conn_weight[i])
            order = []
            for g in groups:
                order.extend(g)
            return order

        candidate_seqs = []
        # Partition-guided orderings (primary)
        candidate_seqs.append(make_partition_order())
        # BFS orderings from high-connectivity blocks
        top_conn = sorted(movable, key=lambda i: -conn_weight[i])[:3]
        for sb in top_conn:
            candidate_seqs.append(make_bfs_order(sb))
        # Other heuristic orderings
        candidate_seqs.append(sorted(movable, key=lambda i: -area_targets[i]))
        candidate_seqs.append(sorted(movable, key=lambda i: -heights[i]))
        for _ in range(4):
            rs = movable[:]
            rng.shuffle(rs)
            candidate_seqs.append(rs)

        # ---- Compact packing: minimize bounding box area ----
        def compact_pack(seq, ws, hs):
            placement = [[0.0, 0.0, 0.0, 0.0] for _ in range(n)]
            placed = []
            cur_max_x = 0.0
            cur_max_y = 0.0

            for i in preplaced_list:
                placement[i] = [target_pos[i][0], target_pos[i][1],
                                target_dims[i][0], target_dims[i][1]]
                placed.append(i)
                cur_max_x = max(cur_max_x,
                                target_pos[i][0] + target_dims[i][0])
                cur_max_y = max(cur_max_y,
                                target_pos[i][1] + target_dims[i][1])

            for block_idx in seq:
                w, h = ws[block_idx], hs[block_idx]
                cand_x = set([0.0])
                for pi in placed:
                    cand_x.add(placement[pi][0] + placement[pi][2])

                best_x = 0.0
                best_y = 0.0
                best_score = float("inf")

                for cx in sorted(cand_x):
                    y = 0.0
                    for pi in placed:
                        bx, by, bw, bh = placement[pi]
                        if cx < bx + bw - 1e-9 and cx + w > bx + 1e-9:
                            if by + bh > y:
                                y = by + bh

                    new_mx = max(cur_max_x, cx + w)
                    new_my = max(cur_max_y, y + h)
                    score = new_mx * new_my

                    if score < best_score:
                        best_score = score
                        best_x = cx
                        best_y = y

                placement[block_idx] = [best_x, best_y, w, h]
                placed.append(block_idx)
                cur_max_x = max(cur_max_x, best_x + w)
                cur_max_y = max(cur_max_y, best_y + h)

            return placement

        # ---- SA cost function ----
        def compute_sa_cost(placement):
            hpwl = 0.0
            for src, dst, w in b2b_edges:
                cx1 = placement[src][0] + placement[src][2] * 0.5
                cy1 = placement[src][1] + placement[src][3] * 0.5
                cx2 = placement[dst][0] + placement[dst][2] * 0.5
                cy2 = placement[dst][1] + placement[dst][3] * 0.5
                hpwl += w * (abs(cx1 - cx2) + abs(cy1 - cy2))
            for pin_idx, block_idx, w in p2b_edges:
                px, py = pin_positions[pin_idx]
                cx = placement[block_idx][0] + placement[block_idx][2] * 0.5
                cy = placement[block_idx][1] + placement[block_idx][3] * 0.5
                hpwl += w * (abs(px - cx) + abs(py - cy))

            min_x = min(p[0] for p in placement)
            min_y = min(p[1] for p in placement)
            max_x = max(p[0] + p[2] for p in placement)
            max_y = max(p[1] + p[3] for p in placement)
            area = (max_x - min_x) * (max_y - min_y)

            penalty = 0.0
            for group in cluster_groups:
                for ai in range(len(group)):
                    pa = placement[group[ai]]
                    nearest = 1e18
                    for bi in range(len(group)):
                        if ai != bi:
                            pb = placement[group[bi]]
                            dx = max(0.0, max(pa[0], pb[0])
                                     - min(pa[0] + pa[2], pb[0] + pb[2]))
                            dy = max(0.0, max(pa[1], pb[1])
                                     - min(pa[1] + pa[3], pb[1] + pb[3]))
                            d = dx + dy
                            if d < nearest:
                                nearest = d
                    penalty += nearest * 50.0

            for i, bitmask in enumerate(boundary_constraints):
                if bitmask == 0:
                    continue
                x, y, bw, bh = placement[i]
                if bitmask & 1:
                    penalty += abs(x - min_x) * 20.0
                if bitmask & 2:
                    penalty += abs(x + bw - max_x) * 20.0
                if bitmask & 4:
                    penalty += abs(y + bh - max_y) * 20.0
                if bitmask & 8:
                    penalty += abs(y - min_y) * 20.0

            return hpwl + area * 0.01 + penalty

        # ---- Pick best initial ordering ----
        best_cost = float("inf")
        best_seq = None
        for seq in candidate_seqs:
            p = compact_pack(seq, widths, heights)
            c = compute_sa_cost(p)
            if c < best_cost:
                best_cost = c
                best_seq = seq[:]

        cur_seq = best_seq[:]
        cur_widths = widths[:]
        cur_heights = heights[:]
        cur_placement = compact_pack(cur_seq, cur_widths, cur_heights)
        cur_cost = best_cost
        best_placement = [list(p) for p in cur_placement]

        # ---- Simulated Annealing ----
        time_limit = 35.0
        t_start = time.time()
        temp = 500.0
        final_temp = 0.5
        cooling = 0.99
        moves_per_temp = max(8, n // 4)
        seq_len = len(cur_seq)

        mib_block_to_group = {}
        for gi, group in enumerate(mib_groups):
            for idx in group:
                mib_block_to_group[idx] = gi

        while temp > final_temp:
            if time.time() - t_start > time_limit:
                break
            for _ in range(moves_per_temp):
                new_seq = cur_seq[:]
                new_widths = cur_widths[:]
                new_heights = cur_heights[:]

                move = rng.randint(0, 4)

                if move == 0 and seq_len >= 2:
                    i = rng.randint(0, seq_len - 1)
                    j = rng.randint(0, seq_len - 1)
                    new_seq[i], new_seq[j] = new_seq[j], new_seq[i]

                elif move == 1 and soft_blocks:
                    idx = rng.choice(soft_blocks)
                    new_widths[idx], new_heights[idx] = (
                        new_heights[idx], new_widths[idx])
                    if idx in mib_block_to_group:
                        gi = mib_block_to_group[idx]
                        for gidx in mib_groups[gi]:
                            if block_types[gidx] == 0:
                                new_widths[gidx] = new_widths[idx]
                                new_heights[gidx] = new_heights[idx]

                elif move == 2 and seq_len >= 2:
                    i = rng.randint(0, seq_len - 1)
                    j = rng.randint(0, seq_len - 1)
                    block = new_seq.pop(i)
                    new_seq.insert(j, block)

                elif move == 3 and soft_blocks:
                    idx = rng.choice(soft_blocks)
                    a = area_targets[idx]
                    ratio = rng.uniform(0.5, 2.0)
                    nw = math.sqrt(a * ratio)
                    nh = a / nw
                    new_widths[idx] = nw
                    new_heights[idx] = nh
                    if idx in mib_block_to_group:
                        gi = mib_block_to_group[idx]
                        for gidx in mib_groups[gi]:
                            if block_types[gidx] == 0:
                                new_widths[gidx] = nw
                                new_heights[gidx] = nh

                elif move == 4 and cluster_groups:
                    group = rng.choice(cluster_groups)
                    gs = set(group)
                    idxs = [si for si in range(seq_len)
                            if new_seq[si] in gs]
                    if len(idxs) >= 2:
                        anchor = idxs[0]
                        blocks = [new_seq[si] for si in
                                  sorted(idxs, reverse=True)]
                        for si in sorted(idxs, reverse=True):
                            new_seq.pop(si)
                        for b in blocks:
                            new_seq.insert(anchor, b)

                new_placement = compact_pack(new_seq, new_widths,
                                              new_heights)
                new_cost = compute_sa_cost(new_placement)
                delta = new_cost - cur_cost

                if delta < 0 or rng.random() < math.exp(
                        -delta / max(temp, 1e-10)):
                    cur_seq = new_seq
                    cur_widths = new_widths
                    cur_heights = new_heights
                    cur_cost = new_cost
                    cur_placement = new_placement
                    if new_cost < best_cost:
                        best_cost = new_cost
                        best_placement = [list(p) for p in new_placement]

            temp *= cooling

        # ---- Post-processing ----
        for i in range(n):
            if block_types[i] == 0:
                actual = best_placement[i][2] * best_placement[i][3]
                target = area_targets[i]
                if target > 0 and abs(actual - target) / target > 0.005:
                    ratio = math.sqrt(target / actual)
                    best_placement[i][2] *= ratio
                    best_placement[i][3] *= ratio

        for group in mib_groups:
            soft_in_group = [i for i in group if block_types[i] == 0]
            if len(soft_in_group) >= 2:
                ref_w = best_placement[soft_in_group[0]][2]
                ref_h = best_placement[soft_in_group[0]][3]
                for idx in soft_in_group[1:]:
                    best_placement[idx][2] = ref_w
                    best_placement[idx][3] = ref_h

        # ---- Write EDA tool outputs ----
        self._write_bookshelf_pl(instance, best_placement)
        self._write_gnuplot_viz(instance, best_placement, partitions, nparts)

        return best_placement
