"""
Pure Python Job Shop Scheduling solver.
Giffler-Thompson active-schedule dispatching + simulated annealing.
Topological-sort evaluation for fast SA iterations.

"""

import json
import math
import os
import random
import sys
import time


def parse_instance(filepath):
    with open(filepath) as f:
        lines = [l.strip() for l in f if l.strip()]
    nj, nm = map(int, lines[0].split())
    jobs = []
    for i in range(1, nj + 1):
        v = list(map(int, lines[i].split()))
        jobs.append([(v[k], v[k + 1]) for k in range(0, len(v), 2)])
    return nj, nm, jobs


class JSPEvaluator:
    """Fast JSP evaluation using Kahn's topological sort."""

    def __init__(self, jobs, nm):
        self.jobs = jobs
        self.nm = nm
        self.nj = nj = len(jobs)
        self.nops = [len(j) for j in jobs]
        self.max_ops = mo = max(self.nops) if self.nops else 0
        self.N = N = nj * mo
        self.total_ops = sum(self.nops)

        self.dur = [0] * N
        for j in range(nj):
            for op in range(self.nops[j]):
                self.dur[j * mo + op] = jobs[j][op][1]

        self._job_succ = [-1] * N
        for j in range(nj):
            for op in range(self.nops[j] - 1):
                self._job_succ[j * mo + op] = j * mo + op + 1

        self._job_in_deg = [0] * N
        for j in range(nj):
            for op in range(1, self.nops[j]):
                self._job_in_deg[j * mo + op] = 1

        self._starts = [0] * N
        self._in_degree = [0] * N
        self._mach_succ = [-1] * N
        self._queue = [0] * N

    def evaluate(self, order):
        N = self.N
        nj = self.nj
        nm = self.nm
        mo = self.max_ops
        nops = self.nops
        dur = self.dur
        starts = self._starts
        in_deg = self._in_degree
        mach_succ = self._mach_succ
        job_succ = self._job_succ
        job_in_deg = self._job_in_deg
        queue = self._queue

        for i in range(N):
            starts[i] = 0
            in_deg[i] = job_in_deg[i]
            mach_succ[i] = -1

        for m in range(nm):
            om = order[m]
            L = len(om)
            for i in range(1, L):
                j, op = om[i]
                in_deg[j * mo + op] += 1
            for i in range(L - 1):
                j, op = om[i]
                jn, opn = om[i + 1]
                mach_succ[j * mo + op] = jn * mo + opn

        qend = 0
        for j in range(nj):
            for op in range(nops[j]):
                idx = j * mo + op
                if in_deg[idx] == 0:
                    queue[qend] = idx
                    qend += 1

        qi = 0
        processed = 0
        while qi < qend:
            idx = queue[qi]
            qi += 1
            processed += 1
            end = starts[idx] + dur[idx]

            js = job_succ[idx]
            if js >= 0:
                if end > starts[js]:
                    starts[js] = end
                in_deg[js] -= 1
                if in_deg[js] == 0:
                    queue[qend] = js
                    qend += 1

            ms = mach_succ[idx]
            if ms >= 0:
                if end > starts[ms]:
                    starts[ms] = end
                in_deg[ms] -= 1
                if in_deg[ms] == 0:
                    queue[qend] = ms
                    qend += 1

        if processed < self.total_ops:
            return 10**9

        makespan = 0
        for j in range(nj):
            last = nops[j] - 1
            idx = j * mo + last
            e = starts[idx] + dur[idx]
            if e > makespan:
                makespan = e
        return makespan

    def build_schedule(self, order):
        ms = self.evaluate(order)
        if ms >= 10**9:
            return None, ms
        starts = self._starts
        mo = self.max_ops
        schedule = {}
        for j in range(self.nj):
            ops = []
            for op in range(self.nops[j]):
                m, d = self.jobs[j][op]
                s = starts[j * mo + op]
                ops.append({"machine": m, "start": s, "duration": d})
            schedule[str(j)] = ops
        return schedule, ms


def giffler_thompson(jobs, nm, rule, rng=None):
    nj = len(jobs)
    nops = [len(j) for j in jobs]
    jnext = [0] * nj
    javail = [0] * nj
    mavail = [0] * nm
    order = [[] for _ in range(nm)]
    total = sum(nops)

    for _ in range(total):
        eligible = []
        for j in range(nj):
            if jnext[j] < nops[j]:
                m, d = jobs[j][jnext[j]]
                s = max(javail[j], mavail[m])
                eligible.append((j, jnext[j], m, d, s, s + d))

        min_end = min(e[5] for e in eligible)
        tm = next(e[2] for e in eligible if e[5] == min_end)
        conflict = [e for e in eligible if e[2] == tm and e[4] < min_end]

        if rule == "SPT":
            conflict.sort(key=lambda x: x[3])
        elif rule == "LPT":
            conflict.sort(key=lambda x: -x[3])
        elif rule == "MWR":
            wr = {}
            for c in conflict:
                j = c[0]
                if j not in wr:
                    wr[j] = sum(d for _, d in jobs[j][jnext[j]:])
            conflict.sort(key=lambda x: -wr[x[0]])
        elif rule == "LWR":
            wr = {}
            for c in conflict:
                j = c[0]
                if j not in wr:
                    wr[j] = sum(d for _, d in jobs[j][jnext[j]:])
            conflict.sort(key=lambda x: wr[x[0]])
        elif rule == "RND" and rng:
            rng.shuffle(conflict)

        j, oi, m, d, s, _ = conflict[0]
        order[m].append((j, oi))
        jnext[j] += 1
        javail[j] = s + d
        mavail[m] = s + d

    return order


def solve_instance(nj, nm, jobs, time_limit_sec):
    evaluator = JSPEvaluator(jobs, nm)
    rng = random.Random(42)
    best_order = None
    best_ms = 10**9

    for rule in ["SPT", "LPT", "MWR", "LWR"]:
        o = giffler_thompson(jobs, nm, rule)
        ms = evaluator.evaluate(o)
        if ms < best_ms:
            best_ms = ms
            best_order = [list(mo) for mo in o]

    for _ in range(5000):
        o = giffler_thompson(jobs, nm, "RND", rng)
        ms = evaluator.evaluate(o)
        if ms < best_ms:
            best_ms = ms
            best_order = [list(mo) for mo in o]

    print(f"  Dispatching best: {best_ms}", flush=True)

    curr_order = [list(mo) for mo in best_order]
    curr_ms = best_ms
    T = best_ms * 0.04
    alpha = 0.99985
    t0 = time.time()
    sa_iters = 0

    while (time.time() - t0) < time_limit_sec:
        m = rng.randint(0, nm - 1)
        L = len(curr_order[m])
        if L < 2:
            continue
        i = rng.randint(0, L - 2)

        curr_order[m][i], curr_order[m][i + 1] = (
            curr_order[m][i + 1],
            curr_order[m][i],
        )
        new_ms = evaluator.evaluate(curr_order)

        delta = new_ms - curr_ms
        if delta <= 0 or (T > 0.01 and rng.random() < math.exp(-delta / max(T, 0.001))):
            curr_ms = new_ms
            if curr_ms < best_ms:
                best_ms = curr_ms
                best_order = [list(mo) for mo in curr_order]
        else:
            curr_order[m][i], curr_order[m][i + 1] = (
                curr_order[m][i + 1],
                curr_order[m][i],
            )

        T *= alpha
        sa_iters += 1

        if sa_iters % 10000 == 0:
            T = max(T, best_ms * 0.015)
            if curr_ms > best_ms * 1.12:
                curr_order = [list(mo) for mo in best_order]
                curr_ms = best_ms

    print(f"  SA: {sa_iters} iters, best: {best_ms}", flush=True)

    schedule, ms = evaluator.build_schedule(best_order)
    return {"makespan": ms, "schedule": schedule}


def main():
    instances = ["ft06", "la01", "ft10", "ft20", "abz7"]
    time_limits = {
        "ft06": 10,
        "la01": 15,
        "ft10": 45,
        "ft20": 45,
        "abz7": 90,
    }
    results = {}

    for name in instances:
        fp = f"/app/data/{name}.txt"
        if not os.path.exists(fp):
            print(f"ERROR: {fp} not found", file=sys.stderr)
            sys.exit(1)

        nj, nm, jobs = parse_instance(fp)
        print(f"Solving {name} ({nj} jobs x {nm} machines)...", flush=True)

        limit = time_limits.get(name, 30)
        results[name] = solve_instance(nj, nm, jobs, limit)
        print(f"  {name}: makespan = {results[name]['makespan']}", flush=True)

        with open("/app/results.json", "w") as f:
            json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json", flush=True)


if __name__ == "__main__":
    main()
