#!/usr/bin/env python3
"""
DAG operational diagnostics analyzer.

Reads YAML DAG definitions, pool configuration, and a SQLite execution
history database, then produces a comprehensive diagnostic report.
"""

import json
import os
import sqlite3
from collections import defaultdict
from itertools import combinations

import yaml


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_dag_configs(dags_dir):
    """Load and return all DAG YAML configs sorted by filename."""
    dags = []
    for fname in sorted(os.listdir(dags_dir)):
        if fname.endswith((".yaml", ".yml")):
            with open(os.path.join(dags_dir, fname)) as fh:
                dags.append(yaml.safe_load(fh))
    return dags


def load_pool_config(path):
    """Load pool configuration YAML."""
    with open(path) as fh:
        return yaml.safe_load(fh).get("pools", {})


# ---------------------------------------------------------------------------
# Dataset dependency graph & cycle detection
# ---------------------------------------------------------------------------

def build_dataset_graph(dags):
    """Build a directed graph over datasets.

    For each DAG, edges go from every consumed dataset to every produced
    dataset.  Returns the adjacency dict, an edge-to-DAGs mapping, and the
    full set of dataset names.
    """
    adj = defaultdict(set)
    edge_dags = defaultdict(list)
    all_datasets = set()

    for dag in dags:
        dag_id = dag["dag_id"]
        consumed = dag.get("datasets", {}).get("consumes", [])
        produced = dag.get("datasets", {}).get("produces", [])
        all_datasets.update(consumed)
        all_datasets.update(produced)
        for c in consumed:
            for p in produced:
                adj[c].add(p)
                edge_dags[(c, p)].append(dag_id)

    return adj, edge_dags, all_datasets


def find_elementary_cycles(adj, all_datasets):
    """Return every elementary (simple) cycle in the directed graph.

    Each cycle is a list of nodes ending with a repeat of the first node.
    Uses Johnson's algorithm (1975).
    """
    nodes = sorted(all_datasets)
    result = []

    def _unblock(u, blocked, block_map):
        blocked.discard(u)
        while block_map[u]:
            w = block_map[u].pop()
            if w in blocked:
                _unblock(w, blocked, block_map)

    def _circuit(v, start, sub_adj, stack, blocked, block_map):
        found = False
        stack.append(v)
        blocked.add(v)

        for w in sorted(sub_adj.get(v, set())):
            if w == start:
                result.append(list(stack) + [start])
                found = True
            elif w not in blocked:
                if _circuit(w, start, sub_adj, stack, blocked, block_map):
                    found = True

        if found:
            _unblock(v, blocked, block_map)
        else:
            for w in sub_adj.get(v, set()):
                block_map[w].add(v)

        stack.pop()
        return found

    for i, start in enumerate(nodes):
        sub_nodes = set(nodes[i:])
        sub_adj = {n: adj.get(n, set()) & sub_nodes for n in sub_nodes}

        blocked = set()
        block_map = defaultdict(set)
        _circuit(start, start, sub_adj, [], blocked, block_map)

    return result


def dags_for_cycle(cycle, edge_dags):
    """Return the set of DAG IDs whose edges participate in *cycle*."""
    dags = set()
    for i in range(len(cycle) - 1):
        key = (cycle[i], cycle[i + 1])
        dags.update(edge_dags.get(key, []))
    return dags


# ---------------------------------------------------------------------------
# Pool bottleneck analysis (theoretical worst-case)
# ---------------------------------------------------------------------------

def peak_pool_demand(dag):
    """Compute peak concurrent pool-slot demand for a DAG.

    Tasks that share no ancestor/descendant relationship can execute in
    parallel; their slot counts must be summed.  The peak is the maximum
    total slots over all antichains in the task dependency partial order.
    """
    tasks = dag.get("tasks", {})
    if not tasks:
        return 0

    names = list(tasks.keys())

    # Build transitive-closure ancestor sets
    upstream = {n: set(tasks[n].get("upstream", [])) for n in names}
    ancestors = {}

    def _ancestors(t):
        if t in ancestors:
            return ancestors[t]
        anc = set()
        for p in upstream[t]:
            anc.add(p)
            anc |= _ancestors(p)
        ancestors[t] = anc
        return anc

    for t in names:
        _ancestors(t)

    def comparable(a, b):
        return a in ancestors[b] or b in ancestors[a]

    best = 0
    for size in range(1, len(names) + 1):
        for subset in combinations(names, size):
            if all(
                not comparable(subset[i], subset[j])
                for i in range(len(subset))
                for j in range(i + 1, len(subset))
            ):
                total = sum(tasks[t]["pool_slots"] for t in subset)
                if total > best:
                    best = total
    return best


def analyze_pools(dags, pools):
    """Return list of pool bottlenecks (demand > capacity)."""
    pool_dag_map = defaultdict(list)
    for dag in dags:
        pool_dag_map[dag.get("default_pool", "default_pool")].append(dag)

    bottlenecks = []
    for pool_name, pcfg in pools.items():
        capacity = pcfg["slots"]
        assigned = pool_dag_map.get(pool_name, [])
        if not assigned:
            continue

        demand = 0
        contributors = []
        for dag in assigned:
            pk = peak_pool_demand(dag)
            if pk > 0:
                demand += pk
                contributors.append(dag["dag_id"])

        if demand > capacity:
            bottlenecks.append({
                "pool": pool_name,
                "capacity": capacity,
                "max_concurrent_demand": demand,
                "contributing_dags": sorted(contributors),
            })

    return bottlenecks


# ---------------------------------------------------------------------------
# Observed pool saturation (from execution history DB)
# ---------------------------------------------------------------------------

def analyze_observed_saturation(db_path, pools):
    """Query execution history to find pools with historical slot saturation.

    Uses a sweep-line over task start/end events to compute peak concurrent
    slot usage per pool.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    saturation = []

    for pool_name, pcfg in pools.items():
        capacity = pcfg["slots"]

        rows = conn.execute(
            "SELECT dag_id, pool_slots, start_ts, end_ts "
            "FROM task_execution WHERE pool = ?",
            (pool_name,),
        ).fetchall()

        if not rows:
            continue

        # Build start/end events: (timestamp, +/- slots, dag_id)
        events = []
        for row in rows:
            events.append((row["start_ts"], row["pool_slots"], row["dag_id"]))
            events.append((row["end_ts"], -row["pool_slots"], row["dag_id"]))

        # Sort: by timestamp, then ends (negative) before starts (positive)
        # This implements half-open intervals [start, end)
        events.sort(key=lambda e: (e[0], e[1]))

        current_usage = 0
        peak_usage = 0
        active_dags = {}  # dag_id -> current slot count
        peak_dags = set()

        for _ts, delta, dag_id in events:
            current_val = active_dags.get(dag_id, 0) + delta
            if current_val <= 0:
                active_dags.pop(dag_id, None)
            else:
                active_dags[dag_id] = current_val

            current_usage += delta

            if current_usage > peak_usage:
                peak_usage = current_usage
                peak_dags = set(active_dags.keys())

        if peak_usage > capacity:
            saturation.append({
                "pool": pool_name,
                "capacity": capacity,
                "peak_concurrent_slots": peak_usage,
                "contributing_dags": sorted(peak_dags),
            })

    conn.close()
    return saturation


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    dags_dir = "/app/dags"
    pools_path = "/app/config/pools.yaml"
    db_path = "/app/metadata.db"
    output_path = "/app/analysis_report.json"

    dags = load_dag_configs(dags_dir)
    pools = load_pool_config(pools_path)

    # Cycle detection
    adj, edge_dags, all_datasets = build_dataset_graph(dags)
    raw_cycles = find_elementary_cycles(adj, all_datasets)

    cycles_report = []
    for cyc in raw_cycles:
        cycles_report.append({
            "cycle": cyc,
            "involved_dags": sorted(dags_for_cycle(cyc, edge_dags)),
        })

    # Theoretical pool analysis
    bottlenecks = analyze_pools(dags, pools)

    # Observed pool saturation from execution history
    saturation = analyze_observed_saturation(db_path, pools)

    report = {
        "dataset_dependency_cycles": cycles_report,
        "pool_bottlenecks": bottlenecks,
        "observed_pool_saturation": saturation,
        "total_dags": len(dags),
        "total_datasets": len(all_datasets),
    }

    with open(output_path, "w") as fh:
        json.dump(report, fh, indent=2)


if __name__ == "__main__":
    main()
