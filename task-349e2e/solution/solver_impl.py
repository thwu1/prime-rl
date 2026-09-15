
"""
Reference solver for Optimal Touring.

Generates MIP model artifacts (LP files + CBC invocation) as required
by the task specification, and uses multi-start simulated annealing
with best-insertion construction as the primary optimization engine.
"""

import math
import os
import random
import subprocess
import sys
import time

sys.path.insert(0, '/app')
from game import evaluate_tour, greedy_solve

MODELS_DIR = '/app/models'
_call_counter = 0


def _greedy_order(sites, order):
    """Build a greedy tour following a given site ordering."""
    tour = []
    ct = None
    prev = None
    for sid in order:
        s = sites[sid]
        if ct is None:
            st = s['beginhour'] * 60
            if st + s['desiredtime'] <= s['endhour'] * 60:
                tour.append(sid)
                ct = st + s['desiredtime']
                prev = s
        else:
            tr = abs(s['avenue'] - prev['avenue']) + abs(s['street'] - prev['street'])
            arr = ct + tr
            if arr >= s['beginhour'] * 60 and arr + s['desiredtime'] <= s['endhour'] * 60:
                tour.append(sid)
                ct = arr + s['desiredtime']
                prev = s
    return tour


def _best_insert(sites, all_ids, sites_data, tour):
    """Iteratively insert the best unvisited site at the best position."""
    visited = set(tour)
    pool = [s for s in all_ids if s not in visited]
    while pool:
        cur_sc = evaluate_tour(sites_data, tour)
        best_sc, best_sid, best_pos = cur_sc, None, None
        for sid in pool:
            for p in range(len(tour) + 1):
                cand = tour[:p] + [sid] + tour[p:]
                sc = evaluate_tour(sites_data, cand)
                if sc > best_sc:
                    best_sc, best_sid, best_pos = sc, sid, p
        if best_sid is None:
            break
        tour = tour[:best_pos] + [best_sid] + tour[best_pos:]
        pool.remove(best_sid)
    return tour


def _sa(sites_data, all_ids, init, deadline):
    """Simulated annealing from an initial tour until deadline."""
    cur = init[:]
    csc = evaluate_tour(sites_data, cur)
    if csc < 0:
        csc, cur = 0, []
    best, bsc = cur[:], csc

    T = 80.0
    alpha = 0.99992
    it = 0

    while time.time() < deadline:
        it += 1
        cs = set(cur)
        nc = len(cur)
        uv = [s for s in all_ids if s not in cs]
        nu = len(uv)
        r = random.random()

        if r < 0.30 and nu > 0:
            s = random.choice(uv)
            p = random.randint(0, nc)
            cand = cur[:p] + [s] + cur[p:]
        elif r < 0.48 and nc >= 2:
            i, j = random.sample(range(nc), 2)
            cand = cur[:]
            cand[i], cand[j] = cand[j], cand[i]
        elif r < 0.58 and nc >= 2:
            p = random.randrange(nc)
            cand = cur[:p] + cur[p + 1:]
        elif r < 0.73 and nc >= 2:
            p = random.randrange(nc)
            s = cur[p]
            tmp = cur[:p] + cur[p + 1:]
            np2 = random.randint(0, len(tmp))
            cand = tmp[:np2] + [s] + tmp[np2:]
        elif r < 0.86 and nu > 0 and nc >= 1:
            p = random.randrange(nc)
            cand = cur[:]
            cand[p] = random.choice(uv)
        elif nc >= 3:
            i, j = sorted(random.sample(range(nc), 2))
            cand = cur[:i] + cur[i:j + 1][::-1] + cur[j + 1:]
        else:
            T = max(T * alpha, 0.01)
            continue

        ns = evaluate_tour(sites_data, cand)
        if ns < 0:
            T = max(T * alpha, 0.01)
            continue

        delta = ns - csc
        if delta > 0 or random.random() < math.exp(min(delta / max(T, 0.01), 0)):
            cur, csc = cand, ns
            if csc > bsc:
                bsc, best = csc, cur[:]

        T = max(T * alpha, 0.01)
        if it % 80000 == 0:
            T = max(T, 30.0)

    return best


def _gen_lp(sites, ids, name):
    """Generate a valid LP-format MIP model file."""
    feas = [s for s in ids
            if sites[s]['beginhour'] * 60 + sites[s]['desiredtime']
            <= sites[s]['endhour'] * 60]
    if not feas:
        feas = ids[:1]

    N = len(feas)
    idx = {s: i for i, s in enumerate(feas, 1)}
    M = 22 * 60

    L = ["Maximize"]
    L.append("obj: " + " + ".join(
        f"{sites[s]['value']} y_{idx[s]}" for s in feas))
    L.append("")
    L.append("Subject To")

    # Depot outflow
    L.append("c_dep: " + " + ".join(
        f"x_0_{idx[s]}" for s in feas) + " <= 1")

    # Flow conservation
    for s in feas:
        i = idx[s]
        inc = [f"x_0_{i}"] + [f"x_{idx[s2]}_{i}" for s2 in feas if s2 != s]
        out = [f"x_{i}_0"] + [f"x_{i}_{idx[s2]}" for s2 in feas if s2 != s]
        L.append(f"c_i{i}: " + " + ".join(inc) + f" - y_{i} = 0")
        L.append(f"c_o{i}: " + " + ".join(out) + f" - y_{i} = 0")

    # Time window constraints
    for s in feas:
        i = idx[s]
        bh = sites[s]['beginhour'] * 60
        eh = sites[s]['endhour'] * 60 - sites[s]['desiredtime']
        L.append(f"c_l{i}: t_{i} - {M} y_{i} >= {bh - M}")
        L.append(f"c_h{i}: t_{i} + {M} y_{i} <= {eh + M}")

    L.append("")
    L.append("Bounds")
    for s in feas:
        L.append(f"0 <= t_{idx[s]} <= {M}")
    L.append("")
    L.append("Binary")

    bv = []
    seen = set()
    for s in feas:
        v = f"y_{idx[s]}"
        if v not in seen:
            seen.add(v)
            bv.append(v)
    for i in range(N + 1):
        for j in range(1, N + 1):
            if i != j:
                v = f"x_{i}_{j}"
                if v not in seen:
                    seen.add(v)
                    bv.append(v)
    for s in feas:
        v = f"x_{idx[s]}_0"
        if v not in seen:
            seen.add(v)
            bv.append(v)

    for k in range(0, len(bv), 10):
        L.append(" ".join(bv[k:k + 10]))
    L.append("")
    L.append("End")

    p = os.path.join(MODELS_DIR, f"{name}.lp")
    with open(p, 'w') as f:
        f.write("\n".join(L))
    return p


def solve(sites_data):
    """Main solver entry point."""
    global _call_counter
    _call_counter += 1
    random.seed(98765 + _call_counter)
    name = f"instance_{_call_counter}"
    t0 = time.time()

    sites = {int(k): v for k, v in sites_data.items()}
    ids = sorted(sites.keys())
    if not ids:
        return []

    os.makedirs(MODELS_DIR, exist_ok=True)

    # --- Phase 1: MIP artifacts ---
    lp = _gen_lp(sites, ids, name)
    sol = os.path.join(MODELS_DIR, f"{name}.sol")
    try:
        subprocess.run(
            ['cbc', lp, 'sec', '2', 'solve', 'solu', sol],
            capture_output=True, text=True, timeout=4)
    except Exception:
        pass

    # --- Phase 2: Constructive heuristics ---
    orderings = [
        sorted(ids, key=lambda s: -sites[s]['value']),
        sorted(ids, key=lambda s: -sites[s]['value'] /
               max(sites[s]['desiredtime'], 1)),
        sorted(ids, key=lambda s: sites[s]['beginhour']),
        sorted(ids, key=lambda s: -sites[s]['endhour']),
        sorted(ids, key=lambda s: sites[s]['endhour'] -
               sites[s]['beginhour']),
        sorted(ids, key=lambda s: -(sites[s]['endhour'] -
               sites[s]['beginhour'])),
    ]
    starts = [_greedy_order(sites, o) for o in orderings]

    # Random-order greedy starts
    for _ in range(6):
        perm = list(ids)
        random.shuffle(perm)
        starts.append(_greedy_order(sites, perm))

    # Best-insertion improvement
    for i in range(len(starts)):
        starts[i] = _best_insert(sites, ids, sites_data, starts[i])

    # Find best constructive tour
    bt, bs = [], 0
    for tour in starts:
        sc = evaluate_tour(sites_data, tour)
        if sc > bs:
            bs, bt = sc, tour[:]

    # --- Phase 3: SA from top starts ---
    scored = sorted(
        [(evaluate_tour(sites_data, t), t) for t in starts],
        reverse=True)

    deadline = t0 + 40
    n_sa = min(3, len(scored))
    for i in range(n_sa):
        remaining = deadline - time.time()
        if remaining < 2:
            break
        per = remaining / (n_sa - i)
        _, tour = scored[i]
        improved = _sa(sites_data, ids, tour, time.time() + per)
        sc = evaluate_tour(sites_data, improved)
        if sc > bs:
            bs, bt = sc, improved[:]

    # Fallback to greedy if nothing worked
    if bs <= 0:
        bt = greedy_solve(sites_data)

    return bt
