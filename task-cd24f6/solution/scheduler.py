#!/usr/bin/env python3

"""
IOPDDL Graph Scheduling Optimizer.
Analyzes computational DAGs and produces optimized execution schedules
by searching over operator fusion, tiling granularity (including split-K),
tensor retention, and traversal ordering strategies.
"""

import json
import math
import sys
from collections import defaultdict, deque


def solve(problem):
    W = problem["widths"]
    H = problem["heights"]
    inp = problem["inputs"]
    out = problem["outputs"]
    costs = problem["base_costs"]
    types = problem["op_types"]
    cap = problem["fast_memory_capacity"]
    bw = problem["slow_memory_bandwidth"]
    nw, nh = problem["native_granularity"]
    nk = nw
    nops = len(types)

    # Build tensor producer map
    prod = {}
    for i in range(nops):
        for t in out[i]:
            prod[t] = i

    # Build op DAG adjacency
    fwd = defaultdict(set)
    rev = defaultdict(set)
    for i in range(nops):
        for t in inp[i]:
            if t in prod:
                p = prod[t]
                fwd[p].add(i)
                rev[i].add(p)

    def topo_sort():
        deg = defaultdict(int)
        for i in range(nops):
            for s in fwd[i]:
                deg[s] += 1
        q = deque(i for i in range(nops) if deg[i] == 0)
        order = []
        while q:
            n = q.popleft()
            order.append(n)
            for s in fwd[n]:
                deg[s] -= 1
                if deg[s] == 0:
                    q.append(s)
        return order

    def classify(ops):
        p, c = set(), set()
        for o in ops:
            for t in out[o]:
                p.add(t)
            for t in inp[o]:
                c.add(t)
        eph = p & c
        return c - p, p - c, eph

    def oom_ok(ops, w, h, k):
        for o in ops:
            ws = 0
            for i, t in enumerate(inp[o]):
                if types[o] == "MatMul":
                    ws += (h * k) if i == 0 else (k * w)
                else:
                    ws += w * h
            for t in out[o]:
                ws += w * h
            if ws > cap:
                return False
        return True

    def eval_sg(ops, w, h, k, trav, retained_in, retain_out_set):
        bi, bo, _ = classify(ops)
        ow = max((W[t] for o in ops for t in out[o]), default=w)
        oh = max((H[t] for o in ops for t in out[o]), default=h)
        n_w = max(1, math.ceil(ow / w))
        n_h = max(1, math.ceil(oh / h))
        ns = n_w * n_h

        n_k = 1
        for o in ops:
            if types[o] == "MatMul":
                K = W[inp[o][0]]
                n_k = max(n_k, math.ceil(K / k))

        comp = 0.0
        for o in ops:
            if types[o] == "Pointwise":
                comp += costs[o]
            else:
                comp += costs[o] * min(k, nk) / nk

        descs = []
        seen = set()
        for o in ops:
            for i, t in enumerate(inp[o]):
                if t not in bi or t in seen:
                    continue
                seen.add(t)
                if types[o] == "MatMul":
                    if i == 0:
                        descs.append((t, "L", W[t]))
                    else:
                        descs.append((t, "R", 0))
                else:
                    descs.append((t, "P", 0))

        order = list(range(ns)) if trav is None else trav
        lat = 0.0
        lr, rr = {}, {}

        for idx in order:
            row, col = idx // n_w, idx % n_w
            for ks in range(n_k):
                fk, lk = (ks == 0), (ks == n_k - 1)
                mi, mo = 0.0, 0.0
                for tid, kind, Kd in descs:
                    ret = tid in retained_in
                    if kind == "L":
                        if fk and not ret and lr.get(tid) != row:
                            mi += h * Kd
                        if fk:
                            lr[tid] = row
                    elif kind == "R":
                        if not ret:
                            pv = rr.get(tid)
                            if not pv or pv[0] != col or pv[1] != ks:
                                mi += k * w
                        rr[tid] = (col, ks)
                    else:
                        if fk and not ret:
                            mi += w * h
                if lk:
                    for t in bo:
                        if t not in retain_out_set:
                            mo += w * h
                mt = (mi + mo) / bw
                lat += max(comp, mt)

        return lat, n_w, n_h

    def make_zigzag(n_w, n_h):
        order = []
        for r in range(n_h):
            if r % 2 == 0:
                order.extend(r * n_w + c for c in range(n_w))
            else:
                order.extend(r * n_w + c for c in range(n_w - 1, -1, -1))
        return order

    def best_config(ops, retained_in=frozenset(), retain_out=frozenset()):
        has_mm = any(types[o] == "MatMul" for o in ops)
        K_max = 1
        if has_mm:
            for o in ops:
                if types[o] == "MatMul":
                    K_max = max(K_max, W[inp[o][0]])

        # Spatial granularity candidates
        sc = set()
        for d in [1, 2, 4, 8]:
            v = nw // d
            if v >= 1:
                sc.add(v)
        # Max fitting for multi-input ops
        max_slots = max(len(inp[o]) + len(out[o]) for o in ops)
        mg = int(math.sqrt(cap / max_slots))
        if 1 <= mg <= nw:
            sc.add(mg)
        if mg > 0 and mg - (mg % 8) >= 1:
            sc.add(mg - (mg % 8))

        # k candidates
        kc = set()
        if has_mm:
            for d in [1, 2, 4, 8, 16]:
                v = K_max // d
                if v >= 1:
                    kc.add(v)
            kc.add(nk)
        else:
            kc = {1}

        best_l = float('inf')
        best_g = None
        best_t = None

        for s in sorted(sc, reverse=True):
            for kv in sorted(kc, reverse=True):
                if not oom_ok(ops, s, s, kv):
                    continue
                l, nw2, nh2 = eval_sg(ops, s, s, kv, None, retained_in, retain_out)
                if l < best_l:
                    best_l = l
                    best_g = [s, s, kv]
                    best_t = None
                if nw2 * nh2 > 1 and has_mm:
                    zz = make_zigzag(nw2, nh2)
                    l2, _, _ = eval_sg(ops, s, s, kv, zz, retained_in, retain_out)
                    if l2 < best_l:
                        best_l = l2
                        best_g = [s, s, kv]
                        best_t = zz

        return best_g, best_t, best_l

    def connected(ops):
        if len(ops) <= 1:
            return True
        s = set(ops)
        adj = defaultdict(set)
        for o in s:
            for x in fwd[o]:
                if x in s:
                    adj[o].add(x)
                    adj[x].add(o)
            for x in rev[o]:
                if x in s:
                    adj[o].add(x)
                    adj[x].add(o)
        vis = set()
        q = deque([ops[0]])
        vis.add(ops[0])
        while q:
            n = q.popleft()
            for nb in adj[n]:
                if nb not in vis:
                    vis.add(nb)
                    q.append(nb)
        return len(vis) == len(s)

    def valid_partition(parts):
        for i, sg in enumerate(parts):
            _, _, eph = classify(sg)
            for j in range(i + 1, len(parts)):
                for o in parts[j]:
                    for t in inp[o]:
                        if t in eph:
                            return False
        return True

    def eval_partition(parts, retain_cfg=None):
        if retain_cfg is None:
            retain_cfg = [[] for _ in parts]
        sgs, grans, rets, travs, lats = [], [], [], [], []
        ri = frozenset()
        total = 0.0
        for i, sg in enumerate(parts):
            rc = frozenset(retain_cfg[i])
            g, t, l = best_config(sg, ri, rc)
            if g is None:
                return None
            sgs.append(list(sg))
            grans.append(g)
            rets.append(list(retain_cfg[i]))
            travs.append(t)
            lats.append(l)
            total += l
            ri = rc
        return {
            "subgraphs": sgs,
            "granularities": grans,
            "tensors_to_retain": rets,
            "traversal_orders": travs,
            "subgraph_latencies": lats,
        }

    # ====== Main optimization ======
    topo = topo_sort()
    best_sol = None
    best_lat = float('inf')

    def try_part(parts, rc=None):
        nonlocal best_sol, best_lat
        if not valid_partition(parts):
            return
        sol = eval_partition(parts, rc)
        if sol is None:
            return
        tl = sum(sol["subgraph_latencies"])
        if tl < best_lat:
            best_lat = tl
            best_sol = sol

    # Strategy 1: All separate
    try_part([[o] for o in topo])

    # Strategy 2: Full fusion
    if connected(topo):
        try_part([list(topo)])

    # Strategy 3: Greedy chain merge
    chain = [[topo[0]]]
    for i in range(1, len(topo)):
        cand = chain[-1] + [topo[i]]
        if connected(cand):
            chain[-1] = cand
        else:
            chain.append([topo[i]])
    if len(chain) != 1:  # Different from full fusion
        try_part(chain)

    # Strategy 4: 2-part and 3-part splits
    if nops <= 15:
        for sp in range(1, nops):
            p1, p2 = topo[:sp], topo[sp:]
            if connected(p1) and connected(p2):
                try_part([p1, p2])
        if nops <= 10:
            for s1 in range(1, nops - 1):
                for s2 in range(s1 + 1, nops):
                    p1, p2, p3 = topo[:s1], topo[s1:s2], topo[s2:]
                    if connected(p1) and connected(p2) and connected(p3):
                        try_part([p1, p2, p3])

    # Strategy 5: Retention on best partition
    if best_sol:
        parts = [sg[:] for sg in best_sol["subgraphs"]]
        for si in range(len(parts) - 1):
            _, bo, _ = classify(parts[si])
            # Try retaining each boundary output tensor
            for t in bo:
                rc = [[] for _ in parts]
                rc[si] = [t]
                try_part(parts, rc)
            # Try retaining all boundary outputs
            if len(bo) > 1:
                rc = [[] for _ in parts]
                rc[si] = list(bo)
                try_part(parts, rc)

    # Strategy 6: Try all 2-part splits with retention
    if nops <= 15:
        for sp in range(1, nops):
            p1, p2 = topo[:sp], topo[sp:]
            if not connected(p1) or not connected(p2):
                continue
            if not valid_partition([p1, p2]):
                continue
            _, bo1, _ = classify(p1)
            for t in bo1:
                try_part([p1, p2], [[t], []])
            if len(bo1) > 1:
                try_part([p1, p2], [list(bo1), []])

    return best_sol


def main():
    if len(sys.argv) != 2:
        print("Usage: scheduler.py <problem.json>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        problem = json.load(f)
    solution = solve(problem)
    if solution is None:
        print(json.dumps({"error": "No valid solution found"}))
        sys.exit(1)
    print(json.dumps(solution))


if __name__ == "__main__":
    main()
