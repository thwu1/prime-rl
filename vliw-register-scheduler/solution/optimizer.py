"""VLIW Optimizer — full solution.

"""

import sys
sys.path.insert(0, '/app')
from machine import OPCODES, UNIT_SLOTS, get_unit


def optimize(instructions, max_regs):
    """Optimize a sequential instruction list for VLIW execution."""

    # Separate halt from working instructions
    work = []
    for inst in instructions:
        if inst["op"] == "halt":
            break
        work.append(inst)

    n = len(work)
    if n == 0:
        return [[{"op": "halt", "dst": -1, "srcs": []}]]

    # Build dependency graph
    last_def = {}
    deps = [set() for _ in range(n)]
    succs = [set() for _ in range(n)]

    last_store = -1
    loads_since_store = []

    for i, inst in enumerate(work):
        for s in inst["srcs"]:
            if s in last_def:
                deps[i].add(last_def[s])
                succs[last_def[s]].add(i)

        if inst["dst"] >= 0 and inst["dst"] in last_def:
            deps[i].add(last_def[inst["dst"]])
            succs[last_def[inst["dst"]]].add(i)

        if inst["op"] == "store":
            if last_store >= 0:
                deps[i].add(last_store)
                succs[last_store].add(i)
            for l in loads_since_store:
                deps[i].add(l)
                succs[l].add(i)
            last_store = i
            loads_since_store = []
        elif inst["op"] == "load":
            if last_store >= 0:
                deps[i].add(last_store)
                succs[last_store].add(i)
            loads_since_store.append(i)

        if inst["dst"] >= 0:
            last_def[inst["dst"]] = i

    # Compute heights (longest path to any sink)
    heights = [0] * n
    remaining_succ_count = [len(succs[i]) for i in range(n)]
    queue = [i for i in range(n) if remaining_succ_count[i] == 0]
    topo_reverse = []

    while queue:
        i = queue.pop(0)
        topo_reverse.append(i)
        for j in deps[i]:
            remaining_succ_count[j] -= 1
            if remaining_succ_count[j] == 0:
                queue.append(j)

    for i in topo_reverse:
        heights[i] = max((heights[j] + 1 for j in succs[i]), default=0)

    # List scheduling (greedy, height-priority)
    dep_count = [len(deps[i]) for i in range(n)]
    ready = sorted(
        [i for i in range(n) if dep_count[i] == 0],
        key=lambda i: -heights[i]
    )

    bundles_indices = []

    while ready:
        bundle = []
        unit_counts = {"alu": 0, "mem": 0, "flow": 0}
        dsts_in_bundle = set()
        rejected = []

        for i in ready:
            inst = work[i]
            unit = get_unit(inst["op"])

            if unit_counts[unit] >= UNIT_SLOTS[unit]:
                rejected.append(i)
                continue

            if inst["dst"] >= 0 and inst["dst"] in dsts_in_bundle:
                rejected.append(i)
                continue

            bundle.append(i)
            unit_counts[unit] += 1
            if inst["dst"] >= 0:
                dsts_in_bundle.add(inst["dst"])

        if not bundle:
            raise RuntimeError("Scheduler deadlock: no instruction fits in bundle")

        newly_ready = []
        for i in bundle:
            for j in succs[i]:
                dep_count[j] -= 1
                if dep_count[j] == 0:
                    newly_ready.append(j)

        ready = sorted(rejected + newly_ready, key=lambda i: -heights[i])
        bundles_indices.append(bundle)

    # Compute live intervals for register allocation
    inst_cycle = {}
    for cycle, bundle in enumerate(bundles_indices):
        for i in bundle:
            inst_cycle[i] = cycle

    vreg_def_time = {}
    vreg_last_use_time = {}
    all_vregs = set()

    for i, inst in enumerate(work):
        cycle = inst_cycle[i]
        if inst["dst"] >= 0:
            v = inst["dst"]
            all_vregs.add(v)
            vreg_def_time[v] = cycle * 2 + 1
        for s in inst["srcs"]:
            all_vregs.add(s)
            use_time = cycle * 2
            if s not in vreg_last_use_time or use_time > vreg_last_use_time[s]:
                vreg_last_use_time[s] = use_time

    intervals = {}
    for v in all_vregs:
        start = vreg_def_time.get(v, 0)
        end = vreg_last_use_time.get(v, start)
        intervals[v] = (start, end)

    # Graph coloring (DSatur)
    vregs_list = sorted(all_vregs)

    adj = {v: set() for v in vregs_list}
    for i in range(len(vregs_list)):
        for j in range(i + 1, len(vregs_list)):
            vi, vj = vregs_list[i], vregs_list[j]
            si, ei = intervals[vi]
            sj, ej = intervals[vj]
            if si <= ej and sj <= ei:
                adj[vi].add(vj)
                adj[vj].add(vi)

    color = {}
    saturation = {v: 0 for v in vregs_list}
    remaining = set(vregs_list)

    while remaining:
        best = max(remaining, key=lambda v: (
            saturation[v],
            len(adj[v] & remaining),
            -intervals[v][0]
        ))
        used_colors = {color[u] for u in adj[best] if u in color}
        c = 0
        while c in used_colors:
            c += 1
        color[best] = c
        remaining.remove(best)
        for u in adj[best]:
            if u in remaining:
                saturation[u] = len({color[w] for w in adj[u] if w in color})

    num_colors = max(color.values()) + 1 if color else 0
    if num_colors > max_regs:
        raise RuntimeError(
            f"Register allocation failed: need {num_colors} but max is {max_regs}"
        )

    # Build final bundles with physical registers
    final_bundles = []
    for bundle in bundles_indices:
        fb = []
        for i in bundle:
            inst = dict(work[i])
            inst["srcs"] = [color[s] for s in inst["srcs"]]
            if inst["dst"] >= 0:
                inst["dst"] = color[inst["dst"]]
            fb.append(inst)
        final_bundles.append(fb)

    final_bundles.append([{"op": "halt", "dst": -1, "srcs": []}])

    return final_bundles
