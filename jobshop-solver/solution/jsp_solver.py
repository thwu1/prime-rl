#!/usr/bin/env python3
"""
Job Shop Scheduling solver using Simulated Annealing with critical-path-based
neighborhood on the disjunctive graph. Solves OR-Library benchmark instances.
"""

import os
import csv
import random
import time
import math
from collections import deque


def parse_instance(filepath):
    with open(filepath) as f:
        lines = [line.strip() for line in f if line.strip()]
    tokens = lines[0].split()
    num_jobs = int(tokens[0])
    num_machines = int(tokens[1])
    jobs = []
    for j in range(num_jobs):
        parts = lines[1 + j].split()
        operations = []
        for k in range(num_machines):
            machine = int(parts[2 * k])
            duration = int(parts[2 * k + 1])
            operations.append((machine, duration))
        jobs.append(operations)
    return num_jobs, num_machines, jobs


class JSPSolver:
    def __init__(self, num_jobs, num_machines, jobs):
        self.J = num_jobs
        self.M = num_machines
        self.jobs = jobs
        self.total_ops = num_jobs * num_machines
        self.op_machine = [[jobs[j][k][0] for k in range(num_machines)]
                           for j in range(num_jobs)]
        self.op_duration = [[jobs[j][k][1] for k in range(num_machines)]
                            for j in range(num_jobs)]

    def greedy_dispatch(self):
        """Build initial machine orderings using earliest-completion dispatch."""
        machine_orders = [[] for _ in range(self.M)]
        next_op = [0] * self.J
        machine_avail = [0] * self.M
        job_avail = [0] * self.J

        for _ in range(self.total_ops):
            best = None
            for j in range(self.J):
                if next_op[j] >= self.M:
                    continue
                op = next_op[j]
                m = self.op_machine[j][op]
                d = self.op_duration[j][op]
                earliest = max(job_avail[j], machine_avail[m])
                completion = earliest + d
                if best is None or completion < best[0]:
                    best = (completion, j, op, m, d, earliest)

            completion, j, op, m, d, earliest = best
            machine_orders[m].append((j, op))
            machine_avail[m] = completion
            job_avail[j] = completion
            next_op[j] = op + 1

        return machine_orders

    def random_dispatch(self):
        """Build initial machine orderings with randomized dispatch."""
        machine_orders = [[] for _ in range(self.M)]
        next_op = [0] * self.J
        machine_avail = [0] * self.M
        job_avail = [0] * self.J

        for _ in range(self.total_ops):
            candidates = []
            for j in range(self.J):
                if next_op[j] >= self.M:
                    continue
                op = next_op[j]
                m = self.op_machine[j][op]
                d = self.op_duration[j][op]
                earliest = max(job_avail[j], machine_avail[m])
                candidates.append((earliest + d, j, op, m, d, earliest))

            candidates.sort()
            k = min(3, len(candidates))
            idx = random.randint(0, k - 1)
            completion, j, op, m, d, earliest = candidates[idx]

            machine_orders[m].append((j, op))
            machine_avail[m] = completion
            job_avail[j] = completion
            next_op[j] = op + 1

        return machine_orders

    def compute_schedule(self, machine_orders):
        """Compute earliest-start schedule via topological sort.

        Returns (start_times, end_times, makespan) or None if infeasible.
        start_times and end_times are flat arrays indexed by j*M + op.
        """
        J, M = self.J, self.M
        total = self.total_ops

        mpos_m = [0] * total
        mpos_p = [0] * total
        for m in range(M):
            for pos, (j, op) in enumerate(machine_orders[m]):
                idx = j * M + op
                mpos_m[idx] = m
                mpos_p[idx] = pos

        in_deg = [0] * total
        succ = [[] for _ in range(total)]

        for j in range(J):
            for op in range(M - 1):
                src = j * M + op
                dst = j * M + op + 1
                succ[src].append(dst)
                in_deg[dst] += 1

        for m in range(M):
            mo = machine_orders[m]
            for pos in range(len(mo) - 1):
                j1, op1 = mo[pos]
                j2, op2 = mo[pos + 1]
                src = j1 * M + op1
                dst = j2 * M + op2
                succ[src].append(dst)
                in_deg[dst] += 1

        queue = deque()
        start = [0] * total
        end = [0] * total

        for i in range(total):
            if in_deg[i] == 0:
                queue.append(i)

        processed = 0
        while queue:
            idx = queue.popleft()
            processed += 1

            j = idx // M
            op = idx % M
            d = self.op_duration[j][op]

            s = 0
            if op > 0:
                s = end[j * M + op - 1]

            m = mpos_m[idx]
            pos = mpos_p[idx]
            if pos > 0:
                pj, pop = machine_orders[m][pos - 1]
                s = max(s, end[pj * M + pop])

            start[idx] = s
            end[idx] = s + d

            for nxt in succ[idx]:
                in_deg[nxt] -= 1
                if in_deg[nxt] == 0:
                    queue.append(nxt)

        if processed != total:
            return None

        makespan = max(end)
        return start, end, makespan

    def find_critical_swaps(self, machine_orders, start, end, makespan):
        """Find swap candidates on the critical path."""
        J, M = self.J, self.M

        mpos = {}
        for m in range(M):
            for pos, (j, op) in enumerate(machine_orders[m]):
                mpos[(j, op)] = (m, pos)

        last_idx = end.index(makespan)
        last_j = last_idx // M
        last_op = last_idx % M

        critical_path = []
        current = (last_j, last_op)
        visited = set()

        while current is not None:
            if current in visited:
                break
            visited.add(current)
            critical_path.append(current)
            j, op = current
            s = start[j * M + op]

            if s == 0:
                break

            nxt = None
            if op > 0 and end[j * M + op - 1] == s:
                nxt = (j, op - 1)

            m, pos = mpos[current]
            if pos > 0:
                pj, pop = machine_orders[m][pos - 1]
                if end[pj * M + pop] == s:
                    nxt = (pj, pop)

            current = nxt

        critical_path.reverse()

        swaps = []
        for i in range(len(critical_path) - 1):
            j1, op1 = critical_path[i]
            j2, op2 = critical_path[i + 1]
            m1, pos1 = mpos[(j1, op1)]
            m2, pos2 = mpos[(j2, op2)]
            if m1 == m2 and pos2 == pos1 + 1:
                swaps.append((m1, pos1))

        return swaps

    def simulated_annealing(self, machine_orders, time_limit):
        """Run SA with critical-path-based neighborhood."""
        result = self.compute_schedule(machine_orders)
        if result is None:
            return machine_orders, float('inf')

        start_arr, end_arr, current_makespan = result
        best_makespan = current_makespan
        best_orders = [list(mo) for mo in machine_orders]

        T = current_makespan * 0.04
        T_min = 0.1
        alpha = 0.9997

        t0 = time.time()

        while time.time() - t0 < time_limit:
            swaps = self.find_critical_swaps(
                machine_orders, start_arr, end_arr, current_makespan
            )

            if swaps:
                m, pos = random.choice(swaps)
            else:
                machines_with_ops = [
                    mi for mi in range(self.M)
                    if len(machine_orders[mi]) >= 2
                ]
                if not machines_with_ops:
                    break
                m = random.choice(machines_with_ops)
                pos = random.randint(0, len(machine_orders[m]) - 2)

            mo = machine_orders[m]
            mo[pos], mo[pos + 1] = mo[pos + 1], mo[pos]

            new_result = self.compute_schedule(machine_orders)

            if new_result is None:
                mo[pos], mo[pos + 1] = mo[pos + 1], mo[pos]
                continue

            new_start, new_end, new_makespan = new_result
            delta = new_makespan - current_makespan

            accept = False
            if delta <= 0:
                accept = True
            elif T > T_min:
                accept = random.random() < math.exp(-delta / T)

            if accept:
                current_makespan = new_makespan
                start_arr = new_start
                end_arr = new_end
                if current_makespan < best_makespan:
                    best_makespan = current_makespan
                    best_orders = [list(mo_i) for mo_i in machine_orders]
            else:
                mo[pos], mo[pos + 1] = mo[pos + 1], mo[pos]

            T *= alpha
            if T < T_min:
                T = best_makespan * 0.02

        return best_orders, best_makespan

    def solve(self, time_limit=30):
        """Solve with multiple restarts, return best schedule."""
        best_makespan = float('inf')
        best_orders = None

        num_restarts = max(3, int(time_limit / 10))
        time_per_restart = time_limit / num_restarts

        for restart in range(num_restarts):
            if restart == 0:
                machine_orders = self.greedy_dispatch()
            else:
                machine_orders = self.random_dispatch()

            orders, makespan = self.simulated_annealing(
                machine_orders, time_per_restart
            )

            if makespan < best_makespan:
                best_makespan = makespan
                best_orders = orders

        result = self.compute_schedule(best_orders)
        start_arr, end_arr, makespan = result
        return start_arr, end_arr, makespan


def write_schedule(filepath, num_jobs, num_machines, jobs, start_arr, end_arr):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    M = num_machines
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["job", "operation", "machine", "start", "end"])
        for j in range(num_jobs):
            for op in range(M):
                machine = jobs[j][op][0]
                idx = j * M + op
                writer.writerow([j, op, machine, start_arr[idx], end_arr[idx]])


def main():
    random.seed(42)

    instances_dir = "/app/instances"
    output_dir = "/app/output"

    # Only solve the four tested instances
    time_limits = {
        "ft06": 10,
        "la01": 25,
        "la02": 25,
        "la03": 25,
    }

    os.makedirs(output_dir, exist_ok=True)

    for name in sorted(time_limits.keys()):
        inst_path = os.path.join(instances_dir, f"{name}.txt")
        if not os.path.exists(inst_path):
            print(f"Instance {name} not found, skipping")
            continue

        print(f"Solving {name}...", end=" ", flush=True)
        num_jobs, num_machines, jobs = parse_instance(inst_path)
        solver = JSPSolver(num_jobs, num_machines, jobs)

        tl = time_limits[name]
        start_arr, end_arr, makespan = solver.solve(time_limit=tl)

        out_path = os.path.join(output_dir, f"{name}.csv")
        write_schedule(out_path, num_jobs, num_machines, jobs, start_arr, end_arr)
        print(f"makespan = {makespan}")


if __name__ == "__main__":
    main()
