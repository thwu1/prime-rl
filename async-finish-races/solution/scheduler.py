#!/usr/bin/env python3
"""Scheduler: greedy list scheduler with bottom-level priority for P=2."""

import csv
import heapq
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, "/app")
from graph_utils import build_graph, load_trace


def compute_bottom_levels(steps, edges):
    """Bottom-level: longest weighted path from node to any sink, inclusive."""
    cost_of = {s["id"]: s["cost"] for s in steps}
    adj = defaultdict(list)
    in_deg = defaultdict(int)
    for u, v, _ in edges:
        adj[u].append(v)
        in_deg[v] += 1

    from collections import deque
    queue = deque()
    for s in steps:
        if in_deg[s["id"]] == 0:
            queue.append(s["id"])
    topo = []
    while queue:
        u = queue.popleft()
        topo.append(u)
        for v in adj[u]:
            in_deg[v] -= 1
            if in_deg[v] == 0:
                queue.append(v)

    bl = {}
    for u in reversed(topo):
        children = adj[u]
        if not children:
            bl[u] = cost_of[u]
        else:
            bl[u] = cost_of[u] + max(bl[v] for v in children)
    return bl


def simulate_schedule(steps, edges, num_processors=2):
    """Event-driven greedy list scheduler."""
    cost_of = {s["id"]: s["cost"] for s in steps}
    bl = compute_bottom_levels(steps, edges)

    succ = defaultdict(list)
    n_preds = defaultdict(int)
    for u, v, _ in edges:
        succ[u].append(v)
        n_preds[v] += 1

    remaining = {s["id"]: n_preds[s["id"]] for s in steps}
    ready = sorted(
        [s["id"] for s in steps if remaining[s["id"]] == 0],
        key=lambda sid: (-bl[sid], sid),
    )

    proc_free_at = [0] * num_processors
    end_time = {}
    result = []
    scheduled = set()
    events = []

    def assign_ready(t):
        while ready:
            free = sorted([p for p in range(num_processors) if proc_free_at[p] <= t])
            if not free:
                break
            sid = ready.pop(0)
            proc = free[0]
            dur = cost_of[sid]
            end = t + dur
            result.append({
                "step_id": sid,
                "processor": proc,
                "start_time": t,
                "end_time": end,
            })
            end_time[sid] = end
            proc_free_at[proc] = end
            scheduled.add(sid)
            if dur > 0:
                heapq.heappush(events, (end, sid))
            else:
                for v in succ[sid]:
                    remaining[v] -= 1
                    if remaining[v] == 0 and v not in scheduled:
                        ready.append(v)
                ready.sort(key=lambda s: (-bl[s], s))

    assign_ready(0)

    while events:
        t = events[0][0]
        batch = []
        while events and events[0][0] == t:
            _, sid = heapq.heappop(events)
            batch.append(sid)

        for sid in batch:
            for v in succ[sid]:
                remaining[v] -= 1
                if remaining[v] == 0 and v not in scheduled:
                    ready.append(v)
        ready.sort(key=lambda s: (-bl[s], s))

        assign_ready(t)

    result.sort(key=lambda x: (x["start_time"], x["step_id"]))
    return result


def main():
    os.makedirs("/app/schedules", exist_ok=True)
    summary = {}

    for i in range(1, 7):
        name = f"trace{i}"
        program = load_trace(f"/app/traces/{name}.json")
        steps, edges = build_graph(program)
        sched = simulate_schedule(steps, edges, num_processors=2)

        csv_path = f"/app/schedules/{name}.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["step_id", "processor", "start_time", "end_time"]
            )
            writer.writeheader()
            for row in sched:
                writer.writerow(row)

        makespan = max(r["end_time"] for r in sched)
        summary[name] = {"makespan": makespan, "processors": 2}

    with open("/app/schedules/summary.json", "w") as f:
        json.dump(summary, f, indent=2)


if __name__ == "__main__":
    main()
