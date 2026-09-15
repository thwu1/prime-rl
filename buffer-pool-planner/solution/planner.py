#!/usr/bin/env python3
"""Buffer memory planner — ILP-based reference implementation.

Reads a computation graph JSON, computes a memory-aware topological schedule,
formulates buffer packing as ILP in CPLEX LP format, solves with CBC,
writes solution JSON.
"""

import json
import sys
import subprocess
import os
import re
from collections import defaultdict


def sanitize_name(name):
    """Sanitize a name for use in LP variable names."""
    return re.sub(r'[^a-zA-Z0-9_]', '_', name)


def solve(graph):
    buffers = graph["buffers"]
    operations = graph["operations"]
    views = graph.get("views", {})

    ops = {op["id"]: op for op in operations}
    op_ids = list(ops.keys())

    if not op_ids:
        return {"schedule": [], "assignments": {}, "pool_sizes": {}}

    # ── Build DAG adjacency ──
    successors = defaultdict(set)
    in_degree = {op_id: 0 for op_id in op_ids}
    for op in operations:
        for dep in op["deps"]:
            successors[dep].add(op["id"])
            in_degree[op["id"]] += 1

    # ── Memory-aware topological sort ──
    # Heuristic: at each step pick the ready op that frees the most
    # net memory (deallocs minus allocs). This naturally serialises
    # independent branches — finishing one before starting another.
    def net_freed(op_id):
        op = ops[op_id]
        freed = sum(buffers[b]["size"] for b in op.get("deallocs", []) if b in buffers)
        alloc = sum(buffers[b]["size"] for b in op.get("allocs", []) if b in buffers)
        return freed - alloc

    ready = sorted([op_id for op_id in op_ids if in_degree[op_id] == 0])
    schedule = []
    remaining = dict(in_degree)

    while ready:
        best = max(ready, key=lambda oid: (net_freed(oid), oid))
        ready.remove(best)
        schedule.append(best)
        for succ in sorted(successors[best]):
            remaining[succ] -= 1
            if remaining[succ] == 0:
                ready.append(succ)

    # ── Compute buffer lifetimes ──
    step_of = {op_id: i for i, op_id in enumerate(schedule)}
    alloc_step = {}
    dealloc_step = {}
    for op in operations:
        s = step_of[op["id"]]
        for b in op.get("allocs", []):
            if b in buffers:
                alloc_step[b] = s
        for b in op.get("deallocs", []):
            if b in buffers:
                dealloc_step[b] = s

    # ── Build per-space interference graph ──
    buf_ids = list(buffers.keys())
    interfering = []
    for i in range(len(buf_ids)):
        for j in range(i + 1, len(buf_ids)):
            bi, bj = buf_ids[i], buf_ids[j]
            if buffers[bi]["memory_space"] != buffers[bj]["memory_space"]:
                continue
            ai, di = alloc_step[bi], dealloc_step[bi]
            aj, dj = alloc_step[bj], dealloc_step[bj]
            if ai <= dj and aj <= di:
                interfering.append((bi, bj))

    # ── Group buffers by memory space ──
    spaces = defaultdict(list)
    for bid in buf_ids:
        spaces[buffers[bid]["memory_space"]].append(bid)

    # ── Solve each memory space via ILP ──
    assignments = {}
    pool_sizes = {}

    for space in sorted(spaces.keys()):
        space_bufs = spaces[space]

        if not space_bufs:
            continue

        # Get interfering pairs for this space
        space_pairs = [(bi, bj) for bi, bj in interfering
                       if buffers[bi]["memory_space"] == space]

        # If no interference, all buffers can reuse offset 0
        if not space_pairs:
            max_size = 0
            for bid in space_bufs:
                assignments[bid] = 0
                max_size = max(max_size, buffers[bid]["size"])
            pool_sizes[space] = max_size
            continue

        # Compute big-M: upper bound on pool size (sum of all sizes + alignment padding)
        M = sum(buffers[bid]["size"] + buffers[bid]["alignment"]
                for bid in space_bufs)

        # Sanitize names for LP variables
        sn = sanitize_name(space)
        var_k = {bid: "k_{}".format(sanitize_name(bid)) for bid in space_bufs}
        pool_var = "P_{}".format(sn)

        # ── Generate CPLEX LP format ──
        lines = []
        lines.append("Minimize")
        lines.append("  obj: {}".format(pool_var))
        lines.append("")
        lines.append("Subject To")

        # Pool size constraints: align_i * k_i + size_i <= P
        for bid in space_bufs:
            a = buffers[bid]["alignment"]
            s = buffers[bid]["size"]
            cname = "pb_{}".format(sanitize_name(bid))
            lines.append("  {}: {} {} - {} <= {}".format(
                cname, a, var_k[bid], pool_var, -s))

        # Non-overlap disjunctive constraints (big-M formulation)
        for idx, (bi, bj) in enumerate(space_pairs):
            ai = buffers[bi]["alignment"]
            si = buffers[bi]["size"]
            aj = buffers[bj]["alignment"]
            sj = buffers[bj]["size"]
            z = "z_{}".format(idx)

            # Either buffer i ends before j starts, or j ends before i starts.
            # ai*ki + si <= aj*kj + M*z  =>  ai*ki - aj*kj - M*z <= -si
            lines.append("  nv_{}_a: {} {} - {} {} - {} {} <= {}".format(
                idx, ai, var_k[bi], aj, var_k[bj], M, z, -si))
            # aj*kj + sj <= ai*ki + M*(1-z)  =>  -ai*ki + aj*kj + M*z <= M-sj
            lines.append("  nv_{}_b: - {} {} + {} {} + {} {} <= {}".format(
                idx, ai, var_k[bi], aj, var_k[bj], M, z, M - sj))

        lines.append("")
        lines.append("Bounds")
        for bid in space_bufs:
            lines.append("  {} >= 0".format(var_k[bid]))
        lines.append("  {} >= 0".format(pool_var))

        lines.append("")
        lines.append("Generals")
        lines.append("  " + " ".join(var_k[bid] for bid in space_bufs))

        if space_pairs:
            lines.append("")
            lines.append("Binary")
            lines.append("  " + " ".join("z_{}".format(i)
                                         for i in range(len(space_pairs))))

        lines.append("")
        lines.append("End")

        lp_content = "\n".join(lines)
        lp_path = "/app/model_{}.lp".format(sn)
        sol_path = "/app/cbc_sol_{}.sol".format(sn)

        with open(lp_path, "w") as f:
            f.write(lp_content)

        # ── Solve with CBC ──
        result = subprocess.run(
            ["cbc", lp_path, "solve", "solu", sol_path],
            capture_output=True, text=True, timeout=120
        )

        if not os.path.exists(sol_path):
            raise RuntimeError(
                "CBC failed to produce solution for space '{}': {}".format(
                    space, result.stderr))

        # ── Parse CBC solution file ──
        var_values = {}
        with open(sol_path) as f:
            for line_num, line in enumerate(f):
                if line_num == 0:
                    # Status line, e.g. "Optimal - objective value 228"
                    if "Infeasible" in line:
                        raise RuntimeError(
                            "ILP infeasible for space '{}'".format(space))
                    continue
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        var_values[parts[1]] = float(parts[2])
                    except ValueError:
                        continue

        # ── Extract offsets from k values ──
        for bid in space_bufs:
            k_val = int(round(var_values.get(var_k[bid], 0)))
            assignments[bid] = k_val * buffers[bid]["alignment"]

        # Compute tight pool size
        max_end = max(assignments[bid] + buffers[bid]["size"]
                      for bid in space_bufs)
        pool_sizes[space] = max_end

    return {
        "schedule": schedule,
        "assignments": assignments,
        "pool_sizes": pool_sizes,
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: buffer_planner.py <graph.json> <solution.json>",
              file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        graph = json.load(f)

    solution = solve(graph)

    with open(sys.argv[2], "w") as f:
        json.dump(solution, f, indent=2)


if __name__ == "__main__":
    main()
