#!/usr/bin/env python3

"""
Architecture analyzer: computes Robert C. Martin package metrics,
detects circular dependencies via Tarjan's SCC, computes minimum
feedback arc set per cycle group, and identifies layer violations.
"""

import json
import os
from collections import defaultdict
from itertools import combinations


def load_data():
    with open("/app/architecture/components.json") as f:
        components_data = json.load(f)
    with open("/app/architecture/dependencies.json") as f:
        deps_data = json.load(f)
    with open("/app/architecture/layer_rules.json") as f:
        rules_data = json.load(f)
    return components_data["components"], deps_data["dependencies"], rules_data


def compute_metrics(components, dependencies):
    ca = defaultdict(int)
    ce = defaultdict(int)
    for dep in dependencies:
        ce[dep["from"]] += 1
        ca[dep["to"]] += 1

    metrics = {}
    for comp in components:
        name = comp["name"]
        ca_val = ca[name]
        ce_val = ce[name]
        total = ca_val + ce_val
        instability = ce_val / total if total > 0 else 0.0
        abstractness = comp["abstract_types"] / (
            comp["abstract_types"] + comp["concrete_types"]
        )
        distance = abs(abstractness + instability - 1.0)
        metrics[name] = {
            "ca": ca_val,
            "ce": ce_val,
            "instability": round(instability, 5),
            "abstractness": round(abstractness, 5),
            "distance": round(distance, 5),
        }
    return metrics


def tarjan_scc(nodes, adj):
    index_counter = [0]
    stack = []
    lowlink = {}
    index = {}
    on_stack = {}
    sccs = []

    def strongconnect(v):
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True

        for w in adj.get(v, []):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif on_stack.get(w, False):
                lowlink[v] = min(lowlink[v], index[w])

        if lowlink[v] == index[v]:
            scc = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == v:
                    break
            sccs.append(scc)

    for v in nodes:
        if v not in index:
            strongconnect(v)

    return sccs


def is_dag(nodes, adj):
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}

    def dfs(v):
        color[v] = GRAY
        for w in adj.get(v, []):
            if w not in color:
                continue
            if color[w] == GRAY:
                return False
            if color[w] == WHITE:
                if not dfs(w):
                    return False
        color[v] = BLACK
        return True

    for v in nodes:
        if color[v] == WHITE:
            if not dfs(v):
                return False
    return True


def compute_min_fas(scc_nodes, all_deps):
    scc_set = set(scc_nodes)
    internal_edges = [
        (d["from"], d["to"])
        for d in all_deps
        if d["from"] in scc_set and d["to"] in scc_set
    ]

    for k in range(1, len(internal_edges) + 1):
        for edges_to_remove in combinations(range(len(internal_edges)), k):
            remove_set = set(edges_to_remove)
            remaining = [
                e for i, e in enumerate(internal_edges) if i not in remove_set
            ]
            adj = defaultdict(list)
            for f, t in remaining:
                adj[f].append(t)
            if is_dag(list(scc_set), adj):
                return k
    return len(internal_edges)


def detect_cycles(components, dependencies):
    comp_names = [c["name"] for c in components]
    adj = defaultdict(list)
    for dep in dependencies:
        adj[dep["from"]].append(dep["to"])

    sccs = tarjan_scc(comp_names, adj)
    cycle_groups = []
    total_in_cycles = 0

    for scc in sccs:
        if len(scc) > 1:
            sorted_scc = sorted(scc)
            min_fas = compute_min_fas(scc, dependencies)
            cycle_groups.append(
                {"components": sorted_scc, "min_edges_to_break": min_fas}
            )
            total_in_cycles += len(scc)

    cycle_groups.sort(key=lambda g: (-len(g["components"]), g["components"][0]))

    return {
        "cycle_groups": cycle_groups,
        "total_components_in_cycles": total_in_cycles,
    }


def detect_violations(components, dependencies, rules_data):
    comp_layers = {c["name"]: c["layer"] for c in components}
    allowed = rules_data["allowed_dependencies"]

    violations = []
    for dep in dependencies:
        from_layer = comp_layers[dep["from"]]
        to_layer = comp_layers[dep["to"]]
        if to_layer not in allowed.get(from_layer, []):
            violations.append(
                {
                    "from": dep["from"],
                    "to": dep["to"],
                    "from_layer": from_layer,
                    "to_layer": to_layer,
                }
            )

    violations.sort(key=lambda v: (v["from"], v["to"]))
    return {"violations": violations, "total_violations": len(violations)}


def main():
    components, dependencies, rules_data = load_data()

    os.makedirs("/app/results", exist_ok=True)

    metrics = compute_metrics(components, dependencies)
    with open("/app/results/metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    cycles = detect_cycles(components, dependencies)
    with open("/app/results/cycles.json", "w") as f:
        json.dump(cycles, f, indent=2)

    violations = detect_violations(components, dependencies, rules_data)
    with open("/app/results/violations.json", "w") as f:
        json.dump(violations, f, indent=2)

    print("Analysis complete. Results written to /app/results/")


if __name__ == "__main__":
    main()
