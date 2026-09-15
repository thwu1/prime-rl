#!/usr/bin/env python3
"""Reference solution for CPU affinity optimization."""

import json
import os
import re
from collections import defaultdict, deque


def read_sysfs():
    cpus = {}
    sysfs = "/app/data/sysfs"
    for entry in sorted(os.listdir(sysfs)):
        if not entry.startswith("cpu") or not entry[3:].isdigit():
            continue
        cpu_id = int(entry[3:])
        d = os.path.join(sysfs, entry)
        cap = int(open(os.path.join(d, "cpu_capacity")).read().strip())
        power = int(open(os.path.join(d, "power", "active_power_mw")).read().strip())
        cache = open(os.path.join(d, "cache", "index2", "shared_cpu_list")).read().strip()

        if cap >= 900:
            ctype = "big"
        elif cap >= 600:
            ctype = "medium"
        else:
            ctype = "little"

        cpus[cpu_id] = {"capacity": cap, "type": ctype, "power_mw": power,
                        "cache_group": cache}
    return cpus


def parse_ftrace():
    task_runtimes = defaultdict(list)
    task_cpus = {}
    wake_deps = set()
    exec_starts = {}
    pid_to_name = {}

    with open("/app/data/trace.txt") as f:
        for line in f:
            if line.lstrip().startswith("#") or not line.strip():
                continue

            if "sched_switch:" in line:
                m = re.search(
                    r'(\d+\.\d+):\s+sched_switch:.*?'
                    r'prev_comm=(\S+)\s+prev_pid=(\d+).*?prev_state=(\S+).*?'
                    r'next_comm=(\S+)\s+next_pid=(\d+)',
                    line)
                if not m:
                    continue
                ts = float(m.group(1)) * 1e6
                prev_comm, prev_pid = m.group(2), int(m.group(3))
                next_comm, next_pid = m.group(5), int(m.group(6))
                cpu_m = re.search(r'\[(\d+)\]', line)
                cpu = int(cpu_m.group(1))

                if prev_pid != 0 and not prev_comm.startswith("swapper"):
                    pid_to_name[prev_pid] = prev_comm
                    if prev_pid in exec_starts:
                        start_ts, start_cpu = exec_starts[prev_pid]
                        runtime = ts - start_ts
                        task_runtimes[prev_comm].append(runtime)
                        task_cpus[prev_comm] = start_cpu
                        del exec_starts[prev_pid]

                if next_pid != 0 and not next_comm.startswith("swapper"):
                    pid_to_name[next_pid] = next_comm
                    exec_starts[next_pid] = (ts, cpu)

            elif "sched_wakeup:" in line:
                waker_m = re.match(r'\s*(\S+)-(\d+)\s+\[', line)
                if not waker_m:
                    continue
                waker_name = waker_m.group(1)
                waker_pid = int(waker_m.group(2))

                wakee_m = re.search(r'comm=(\S+)\s+pid=(\d+)', line)
                if not wakee_m:
                    continue
                wakee_name = wakee_m.group(1)

                if waker_name.startswith("swapper") or waker_name == "<idle>" or waker_pid == 0:
                    continue

                pid_to_name[waker_pid] = waker_name
                wake_deps.add((waker_name, wakee_name))

    tasks = {}
    for name, rts in task_runtimes.items():
        tasks[name] = {
            "pid": next((p for p, n in pid_to_name.items() if n == name), 0),
            "avg_runtime": sum(rts) / len(rts),
            "total_runtime": sum(rts),
            "cpu": task_cpus.get(name, 0),
        }
    return tasks, wake_deps, pid_to_name


def compute_base_runtimes(tasks, cpus):
    base = {}
    for name, info in tasks.items():
        cap = cpus[info["cpu"]]["capacity"]
        base[name] = {
            "avg": info["avg_runtime"] * cap / 1024,
            "total": info["total_runtime"] * cap / 1024,
        }
    return base


def parse_cpu_range(s):
    result = []
    for part in str(s).split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            result.extend(range(int(lo), int(hi) + 1))
        else:
            result.append(int(part))
    return result


def build_dag(deps, task_names):
    adj = defaultdict(list)
    in_deg = {n: 0 for n in task_names}
    for src, dst in deps:
        if src in task_names and dst in task_names:
            adj[src].append(dst)
            in_deg[dst] += 1
    return adj, in_deg


def topo_sort(task_names, adj, in_deg):
    temp = dict(in_deg)
    order = []
    q = deque(n for n in task_names if temp[n] == 0)
    while q:
        n = q.popleft()
        order.append(n)
        for nb in adj[n]:
            temp[nb] -= 1
            if temp[nb] == 0:
                q.append(nb)
    return order


def longest_path_with_trace(task_names, adj, in_deg, weights):
    topo = topo_sort(task_names, adj, in_deg)
    dist = {n: weights.get(n, 0) for n in task_names}
    parent = {n: None for n in task_names}
    for node in topo:
        for nb in adj[node]:
            nd = dist[node] + weights.get(nb, 0)
            if nd > dist[nb]:
                dist[nb] = nd
                parent[nb] = node
    end = max(dist, key=dist.get)
    path = []
    cur = end
    while cur is not None:
        path.append(cur)
        cur = parent[cur]
    path.reverse()
    return max(dist.values()), path


def compute_frame_time(base_rts, assignments, cpus, deps, task_names):
    weights = {}
    for name in task_names:
        if name not in assignments:
            continue
        cap = cpus[parse_cpu_range(assignments[name])[0]]["capacity"]
        weights[name] = base_rts[name]["avg"] * 1024 / cap
    adj, in_deg = build_dag(deps, task_names)
    ft, _ = longest_path_with_trace(task_names, adj, in_deg, weights)
    return ft


def compute_energy(base_rts, assignments, cpus, task_names):
    energy = 0.0
    for name in task_names:
        if name not in assignments:
            continue
        assigned = parse_cpu_range(assignments[name])
        cap = cpus[assigned[0]]["capacity"]
        power_w = cpus[assigned[0]]["power_mw"] / 1000.0
        total_runtime_s = (base_rts[name]["total"] * 1024 / cap) / 1e6
        energy += power_w * total_runtime_s
    return energy


def main():
    cpus = read_sysfs()
    tasks, deps, pid_map = parse_ftrace()
    base_rts = compute_base_runtimes(tasks, cpus)

    with open("/app/data/requirements.json") as f:
        reqs = json.load(f)
    with open("/app/data/affinity.json") as f:
        cur_affinity = json.load(f)

    target_ft = reqs["target_frame_time_us"]
    budget = reqs["energy_budget_joules"]
    task_names = list(tasks.keys())

    # --- Topology output ---
    topo_out = {"cpus": {}}
    for cpu_id, info in sorted(cpus.items()):
        topo_out["cpus"][str(cpu_id)] = {
            "capacity": info["capacity"],
            "type": info["type"],
            "power_mw": info["power_mw"],
        }

    # --- Task analysis output ---
    deps_on = defaultdict(list)
    deps_by = defaultdict(list)
    for src, dst in deps:
        deps_on[dst].append(src)
        deps_by[src].append(dst)

    task_out = {"tasks": {}}
    for name, info in tasks.items():
        task_out["tasks"][name] = {
            "pid": info["pid"],
            "avg_runtime_us": round(info["avg_runtime"], 2),
            "depends_on": sorted(deps_on.get(name, [])),
            "depended_by": sorted(deps_by.get(name, [])),
        }

    # --- Diagnosis ---
    cur_assign = cur_affinity["assignments"]
    cur_ft = compute_frame_time(base_rts, cur_assign, cpus, deps, task_names)
    cur_energy = compute_energy(base_rts, cur_assign, cpus, task_names)

    diag = {
        "current_frame_time_us": round(cur_ft, 2),
        "target_frame_time_us": target_ft,
        "current_energy_joules": round(cur_energy, 6),
        "energy_budget_joules": budget,
        "frame_time_met": cur_ft <= target_ft,
        "energy_met": cur_energy <= budget,
    }

    # --- Optimization ---
    adj, in_deg = build_dag(deps, task_names)
    base_weights = {n: base_rts[n]["avg"] for n in task_names}
    _, crit_path = longest_path_with_trace(task_names, adj, in_deg, base_weights)
    crit_set = set(crit_path)

    # Start: critical path on big cores, everything else on little cores
    opt = {}
    for name in task_names:
        opt[name] = "0-3" if name in crit_set else "8-11"

    # Check if secondary paths are now critical
    ft = compute_frame_time(base_rts, opt, cpus, deps, task_names)
    if ft > target_ft:
        for name in task_names:
            if name not in crit_set:
                opt[name] = "4-7"
                ft = compute_frame_time(base_rts, opt, cpus, deps, task_names)
                if ft <= target_ft:
                    break

    # If still over, put all non-critical on medium
    if compute_frame_time(base_rts, opt, cpus, deps, task_names) > target_ft:
        for name in task_names:
            if name not in crit_set:
                opt[name] = "4-7"

    # Downgrade non-critical tasks to little to save energy
    for name in task_names:
        if name not in crit_set:
            old = opt[name]
            opt[name] = "8-11"
            if compute_frame_time(base_rts, opt, cpus, deps, task_names) > target_ft:
                opt[name] = "4-7"
                if compute_frame_time(base_rts, opt, cpus, deps, task_names) > target_ft:
                    opt[name] = old

    opt_ft = compute_frame_time(base_rts, opt, cpus, deps, task_names)
    opt_energy = compute_energy(base_rts, opt, cpus, task_names)

    # --- Write outputs ---
    os.makedirs("/app/output", exist_ok=True)

    with open("/app/output/topology.json", "w") as f:
        json.dump(topo_out, f, indent=2)

    with open("/app/output/task_analysis.json", "w") as f:
        json.dump(task_out, f, indent=2)

    with open("/app/output/diagnosis.json", "w") as f:
        json.dump(diag, f, indent=2)

    with open("/app/output/affinity.json", "w") as f:
        json.dump({"assignments": opt}, f, indent=2)

    with open("/app/output/metrics.json", "w") as f:
        json.dump({
            "projected_frame_time_us": round(opt_ft, 2),
            "projected_energy_joules": round(opt_energy, 6),
            "frame_time_met": opt_ft <= target_ft,
            "energy_met": opt_energy <= budget,
        }, f, indent=2)

    print("Solution complete.")
    print("Critical path: {}".format(crit_path))
    print("Current:   FT={:.1f}us (target={}), Energy={:.4f}J (budget={})".format(
        cur_ft, target_ft, cur_energy, budget))
    print("Optimized: FT={:.1f}us, Energy={:.4f}J".format(opt_ft, opt_energy))
    for name in sorted(task_names):
        print("  {} -> {}".format(name, opt[name]))


if __name__ == "__main__":
    main()
