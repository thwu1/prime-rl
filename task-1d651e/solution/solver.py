#!/usr/bin/env python3
"""
Reference solver for facility location optimization pipeline.
Reads scenario configs, solves each instance with greedy+local search,
computes LP relaxation bounds via glpsol where required, writes output files.
"""
import sys
import os
import json
import time
import re
import subprocess
import math
import glob
import numpy as np

SCENARIO_DIR = "/app/data/scenarios"
INSTANCE_DIR = "/app/data/instances"
OUTPUT_DIR = "/app/output"


def parse_instance(filepath):
    with open(filepath) as f:
        lines = f.read().strip().split("\n")
    N, M = map(int, lines[0].split())

    setup = np.zeros(N, dtype=np.float64)
    capacity = np.zeros(N, dtype=np.int64)
    fx = np.zeros(N, dtype=np.float64)
    fy = np.zeros(N, dtype=np.float64)
    for i in range(N):
        p = lines[1 + i].split()
        setup[i] = float(p[0])
        capacity[i] = int(float(p[1]))
        fx[i] = float(p[2])
        fy[i] = float(p[3])

    demand = np.zeros(M, dtype=np.int64)
    cx = np.zeros(M, dtype=np.float64)
    cy = np.zeros(M, dtype=np.float64)
    for j in range(M):
        p = lines[1 + N + j].split()
        demand[j] = int(float(p[0]))
        cx[j] = float(p[1])
        cy[j] = float(p[2])

    return N, M, setup, capacity, fx, fy, demand, cx, cy


def compute_lp_bound(N, M, setup, capacity, fx, fy, demand, cx, cy):
    """Generate CPLEX LP file and solve LP relaxation with glpsol."""
    dist = np.sqrt(
        (fx[:, None] - cx[None, :]) ** 2 + (fy[:, None] - cy[None, :]) ** 2
    )

    lp_file = os.path.join(OUTPUT_DIR, "relaxation.lp")
    sol_file = "/tmp/glpk_lp_solution.txt"

    with open(lp_file, "w") as f:
        f.write("\\* Facility Location LP Relaxation *\\\n\n")
        f.write("minimize\n obj:")
        for i in range(N):
            f.write(f" + {setup[i]:.6f} y{i}")
        for i in range(N):
            for j in range(M):
                f.write(f" + {dist[i, j]:.6f} x{i}_{j}")
        f.write("\n\nsubject to\n")

        for j in range(M):
            terms = " + ".join(f"x{i}_{j}" for i in range(N))
            f.write(f" assign_{j}: {terms} = 1\n")

        for i in range(N):
            parts = []
            for j in range(M):
                parts.append(f"{int(demand[j])} x{i}_{j}")
            f.write(f" cap_{i}: " + " + ".join(parts) + f" - {int(capacity[i])} y{i} <= 0\n")

        f.write("\nbounds\n")
        for i in range(N):
            f.write(f" 0 <= y{i} <= 1\n")
        for i in range(N):
            for j in range(M):
                f.write(f" 0 <= x{i}_{j} <= 1\n")
        f.write("\nend\n")

    try:
        subprocess.run(
            ["glpsol", "--lp", lp_file, "-o", sol_file, "--tmlim", "120"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        with open(sol_file) as f:
            content = f.read()
        match = re.search(r"Objective:.*=\s*([\d.eE+-]+)", content)
        if match:
            return float(match.group(1))
    except Exception as e:
        print(f"  GLPK error: {e}", file=sys.stderr)
    return -1


def solve_heuristic(N, M, setup, capacity, fx, fy, demand, cx, cy, time_limit=80):
    """Greedy construction + local search + iterated local search."""
    t0 = time.time()
    rng = np.random.RandomState(42)

    dist = np.sqrt(
        (fx[:, None] - cx[None, :]) ** 2 + (fy[:, None] - cy[None, :]) ** 2
    )

    K = min(50, N)
    nearest_k = np.argsort(dist, axis=0)[:K, :].T  # (M, K)

    if N <= 300:
        fac_dist = np.sqrt(
            (fx[:, None] - fx[None, :]) ** 2 + (fy[:, None] - fy[None, :]) ** 2
        )
    else:
        fac_dist = None

    # ---- Greedy construction ----
    assign = np.full(M, -1, dtype=np.int64)
    cap_rem = capacity.copy()
    count = np.zeros(N, dtype=np.int64)

    for j in np.argsort(-demand):
        j = int(j)
        best_f, best_cost = -1, np.inf
        for k in range(K):
            f = int(nearest_k[j, k])
            if cap_rem[f] < demand[j]:
                continue
            c = dist[f, j] + (setup[f] if count[f] == 0 else 0)
            if c < best_cost:
                best_cost, best_f = c, f
        if best_f == -1:
            fi = np.where(cap_rem >= demand[j])[0]
            if len(fi) == 0:
                raise RuntimeError(f"Infeasible for customer {j}")
            costs = dist[fi, j] + np.where(count[fi] == 0, setup[fi], 0)
            best_f = int(fi[np.argmin(costs)])
        assign[j] = best_f
        cap_rem[best_f] -= demand[j]
        count[best_f] += 1

    def obj_val():
        return float(setup[count > 0].sum() + dist[assign, np.arange(M)].sum())

    def sync_state():
        cap_rem[:] = capacity
        count[:] = 0
        for j2 in range(M):
            cap_rem[assign[j2]] -= demand[j2]
            count[assign[j2]] += 1

    best_obj = obj_val()
    best_assign = assign.copy()

    # ---- Customer reassignment ----
    def customer_reassignment(max_passes=200):
        nonlocal best_obj, best_assign
        for _ in range(max_passes):
            if time.time() - t0 > time_limit:
                break
            improved = False
            for j in rng.permutation(M):
                j = int(j)
                cur = assign[j]
                cur_d = dist[cur, j]
                bd, bf = -1e-6, -1
                for k in range(K):
                    f = int(nearest_k[j, k])
                    if f == cur or cap_rem[f] < demand[j]:
                        continue
                    delta = dist[f, j] - cur_d
                    if count[f] == 0:
                        delta += setup[f]
                    if count[cur] == 1:
                        delta -= setup[cur]
                    if delta < bd:
                        bd, bf = delta, f
                if bf >= 0:
                    cap_rem[cur] += demand[j]
                    count[cur] -= 1
                    assign[j] = bf
                    cap_rem[bf] -= demand[j]
                    count[bf] += 1
                    improved = True
                if time.time() - t0 > time_limit:
                    break
            o = obj_val()
            if o < best_obj:
                best_obj, best_assign = o, assign.copy()
            if not improved:
                break

    # ---- Facility open ----
    def facility_open_pass():
        nonlocal best_obj, best_assign
        changed = False
        closed = np.where(count == 0)[0]
        if len(closed) == 0:
            return False
        ct = dist[assign, np.arange(M)]
        for fi in closed:
            fi = int(fi)
            if time.time() - t0 > time_limit:
                break
            sp = ct - dist[fi, np.arange(M)]
            ben = np.where(sp > 0)[0]
            if len(ben) == 0:
                continue
            order = ben[np.argsort(-sp[ben])]
            ts, tm, cu = 0.0, [], 0
            for j in order:
                j = int(j)
                if cu + demand[j] > capacity[fi]:
                    continue
                extra = setup[assign[j]] if count[assign[j]] == 1 else 0.0
                ts += sp[j] + extra
                tm.append(j)
                cu += demand[j]
            if ts - setup[fi] > 0.01 and tm:
                for j in tm:
                    cap_rem[assign[j]] += demand[j]
                    count[assign[j]] -= 1
                    assign[j] = fi
                cap_rem[fi] -= cu
                count[fi] = len(tm)
                ct = dist[assign, np.arange(M)]
                changed = True
        o = obj_val()
        if o < best_obj:
            best_obj, best_assign = o, assign.copy()
        return changed

    # ---- Facility close ----
    def facility_close_pass():
        nonlocal best_obj, best_assign
        changed = False
        ofacs = np.where(count > 0)[0]
        for fi in ofacs[np.argsort(count[ofacs])]:
            fi = int(fi)
            if count[fi] == 0 or time.time() - t0 > time_limit:
                continue
            custs = np.where(assign == fi)[0]
            if len(custs) == 0:
                continue
            sav = -setup[fi]
            plan, tc, no = [], cap_rem.copy(), set()
            tc[fi] += demand[custs].sum()
            ok = True
            for c in custs:
                c = int(c)
                ba, bd2 = -1, np.inf
                for k in range(K):
                    a = int(nearest_k[c, k])
                    if a == fi or tc[a] < demand[c]:
                        continue
                    d = dist[a, c] - dist[fi, c]
                    if count[a] == 0 and a not in no:
                        d += setup[a]
                    if d < bd2:
                        bd2, ba = d, a
                if ba == -1:
                    ok = False
                    break
                sav += bd2
                plan.append((c, ba))
                tc[ba] -= demand[c]
                if count[ba] == 0:
                    no.add(ba)
            if ok and sav < -0.01:
                for c, nf in plan:
                    cap_rem[assign[c]] += demand[c]
                    count[assign[c]] -= 1
                    assign[c] = nf
                    cap_rem[nf] -= demand[c]
                    count[nf] += 1
                changed = True
        o = obj_val()
        if o < best_obj:
            best_obj, best_assign = o, assign.copy()
        return changed

    # ---- Facility swap (small instances) ----
    def facility_swap_pass():
        nonlocal best_obj, best_assign
        if N > 300:
            return False
        changed = False
        ofacs = np.where(count > 0)[0]
        cfacs = np.where(count == 0)[0]
        if len(cfacs) == 0:
            return False
        for fo in ofacs:
            fo = int(fo)
            if time.time() - t0 > time_limit:
                break
            custs_o = np.where(assign == fo)[0]
            if len(custs_o) == 0:
                continue
            near_closed = cfacs[np.argsort(fac_dist[fo, cfacs])[:20]]
            bsd, bsf, bsp = -0.01, -1, None
            for fn in near_closed:
                fn = int(fn)
                if count[fn] > 0:
                    continue
                delta = setup[fn] - setup[fo]
                plan, tc = [], cap_rem.copy()
                tc[fo] += demand[custs_o].sum()
                ok = True
                for c in custs_o:
                    c = int(c)
                    bt, bd2 = fn, dist[fn, c]
                    for f2 in ofacs:
                        f2 = int(f2)
                        if f2 == fo:
                            continue
                        if tc[f2] >= demand[c] and dist[f2, c] < bd2:
                            bd2, bt = dist[f2, c], f2
                    if bt == fn and tc[fn] < demand[c]:
                        ok = False
                        break
                    delta += bd2 - dist[fo, c]
                    plan.append((c, bt))
                    tc[bt] -= demand[c]
                if ok and delta < bsd:
                    bsd, bsf, bsp = delta, fn, plan[:]
            if bsf >= 0:
                for c, nf in bsp:
                    cap_rem[assign[c]] += demand[c]
                    count[assign[c]] -= 1
                    assign[c] = nf
                    cap_rem[nf] -= demand[c]
                    count[nf] += 1
                changed = True
        o = obj_val()
        if o < best_obj:
            best_obj, best_assign = o, assign.copy()
        return changed

    # ---- Main optimization loop ----
    customer_reassignment()
    for _ in range(10):
        if time.time() - t0 > time_limit * 0.35:
            break
        c1 = facility_swap_pass()
        c2 = facility_open_pass()
        c3 = facility_close_pass()
        if c1 or c2 or c3:
            customer_reassignment(max_passes=50)
        else:
            break

    # ---- Iterated local search ----
    ils = 0
    while time.time() - t0 < time_limit * 0.95:
        ils += 1
        sa = assign.copy()

        if ils % 3 == 0 and N <= 300:
            ofacs = np.where(count > 0)[0]
            cfacs = np.where(count == 0)[0]
            if len(ofacs) > 0 and len(cfacs) > 0:
                fo = int(rng.choice(ofacs))
                fn = int(rng.choice(cfacs))
                for c in np.where(assign == fo)[0]:
                    c = int(c)
                    cap_rem[fo] += demand[c]
                    count[fo] -= 1
                    assign[c] = fn
                    cap_rem[fn] -= demand[c]
                    count[fn] += 1
        else:
            ps = max(5, M // 8)
            vict = rng.choice(M, min(ps, M), replace=False)
            for j in vict:
                j = int(j)
                cap_rem[assign[j]] += demand[j]
                count[assign[j]] -= 1
            rev = False
            for j in vict:
                j = int(j)
                fi = np.where(cap_rem >= demand[j])[0]
                if len(fi) == 0:
                    assign[:] = sa
                    sync_state()
                    rev = True
                    break
                costs = dist[fi, j]
                w = np.exp(-costs / (costs.mean() + 1e-9))
                w /= w.sum()
                f = int(fi[rng.choice(len(fi), p=w)])
                assign[j] = f
                cap_rem[f] -= demand[j]
                count[f] += 1
            if rev:
                continue

        customer_reassignment(max_passes=30)
        facility_open_pass()
        facility_close_pass()
        customer_reassignment(max_passes=20)

        o = obj_val()
        if o >= best_obj:
            assign[:] = best_assign
            sync_state()
        else:
            best_obj, best_assign = o, assign.copy()

    return best_obj, best_assign


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load all scenario configurations
    scenarios = []
    for sf in sorted(glob.glob(os.path.join(SCENARIO_DIR, "*.json"))):
        with open(sf) as fh:
            scenarios.append(json.load(fh))

    for cfg in scenarios:
        name = cfg["name"]
        instance_file = os.path.join(INSTANCE_DIR, cfg["instance_file"])
        threshold = cfg["max_objective"]
        tl = cfg.get("time_limit_sec", 90)
        need_lp = cfg.get("require_lp_bound", False)

        print(f"Processing {name}...")

        N, M, setup, cap, fx, fy, dem, cx, cy = parse_instance(instance_file)

        # Compute LP bound if required
        lp_bound = -1
        if need_lp:
            print(f"  Computing LP relaxation bound via glpsol...")
            lp_bound = compute_lp_bound(N, M, setup, cap, fx, fy, dem, cx, cy)
            print(f"  LP bound: {lp_bound:.4f}")

        # Solve with heuristic
        print(f"  Running heuristic solver (time limit: {tl - 10}s)...")
        obj, assignment = solve_heuristic(
            N, M, setup, cap, fx, fy, dem, cx, cy, time_limit=tl - 10
        )
        print(f"  Objective: {obj:.4f} (threshold: {threshold})")

        # Write solution file
        sol_file = os.path.join(OUTPUT_DIR, f"{name}.sol")
        with open(sol_file, "w") as f:
            f.write(f"{obj:.4f} 0\n")
            f.write(" ".join(str(int(a)) for a in assignment) + "\n")
            if lp_bound > 0:
                f.write(f"LP_BOUND {lp_bound:.6f}\n")

        print(f"  Written to {sol_file}")

    print("\nAll scenarios processed.")


if __name__ == "__main__":
    main()
