#!/usr/bin/env python3

"""Correct architecture governance analyzer.

Fixes three bugs in the original pipeline:
1. DOT parser regex now handles edges with Graphviz attributes
2. Abstractness uses abstract_types (not concrete_types) in numerator
3. Minimum feedback arc set uses proper brute-force instead of heuristic
"""

import json
import os
import re
import sqlite3
from collections import defaultdict
from itertools import combinations

import yaml


def parse_dot_file(filepath):
    """Parse DOT file, correctly handling edges with attributes."""
    edges = []
    with open(filepath) as f:
        content = f.read()

    # Fixed regex: optionally match [attributes] before the semicolon
    pattern = r'"([^"]+)"\s*->\s*"([^"]+)"\s*(?:\[.*?\])?\s*;'

    for match in re.finditer(pattern, content):
        source = match.group(1)
        target = match.group(2)
        edges.append({"from": source, "to": target})

    return edges


def load_components(db_path):
    """Load component metadata from SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT name, layer, abstract_types, concrete_types FROM components"
    )
    components = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return components


def load_rules(yaml_path):
    """Load layer dependency rules from YAML governance config."""
    with open(yaml_path) as f:
        config = yaml.safe_load(f)
    return config["layer_rules"]


def compute_metrics(components, dependencies):
    """Compute Robert C. Martin package coupling metrics."""
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

        # Correct: abstractness = abstract_types / total_types
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
    """Find all strongly connected components using Tarjan's algorithm."""
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
    """Check if a directed graph is acyclic."""
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
    """Compute minimum feedback arc set size via brute-force enumeration."""
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
    """Detect circular dependencies and compute cycle-breaking costs."""
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
            cycle_groups.append({
                "components": sorted_scc,
                "min_edges_to_break": min_fas
            })
            total_in_cycles += len(scc)

    cycle_groups.sort(key=lambda g: (-len(g["components"]), g["components"][0]))

    return {
        "cycle_groups": cycle_groups,
        "total_components_in_cycles": total_in_cycles,
    }


def detect_violations(components, dependencies, allowed_deps):
    """Identify dependencies that violate layer architecture rules."""
    comp_layers = {c["name"]: c["layer"] for c in components}

    violations = []
    for dep in dependencies:
        from_layer = comp_layers.get(dep["from"])
        to_layer = comp_layers.get(dep["to"])
        if from_layer and to_layer:
            if to_layer not in allowed_deps.get(from_layer, []):
                violations.append({
                    "from": dep["from"],
                    "to": dep["to"],
                    "from_layer": from_layer,
                    "to_layer": to_layer,
                })

    violations.sort(key=lambda v: (v["from"], v["to"]))
    return {"violations": violations, "total_violations": len(violations)}


def main():
    data_dir = "/app/data"
    results_dir = "/app/results"

    # Parse dependencies from DOT file (with correct regex)
    dependencies = parse_dot_file(os.path.join(data_dir, "dependencies.dot"))
    print(f"Parsed {len(dependencies)} edges from DOT file")

    # Load component metadata from SQLite
    components = load_components(os.path.join(data_dir, "components.db"))
    print(f"Loaded {len(components)} components from SQLite")

    # Load governance rules from YAML
    allowed_deps = load_rules(os.path.join(data_dir, "governance.yaml"))

    os.makedirs(results_dir, exist_ok=True)

    # Compute and write metrics
    metrics = compute_metrics(components, dependencies)
    with open(os.path.join(results_dir, "metrics.json"), 'w') as f:
        json.dump(metrics, f, indent=2)

    # Detect and write cycles
    cycles = detect_cycles(components, dependencies)
    with open(os.path.join(results_dir, "cycles.json"), 'w') as f:
        json.dump(cycles, f, indent=2)

    # Detect and write violations
    violations = detect_violations(components, dependencies, allowed_deps)
    with open(os.path.join(results_dir, "violations.json"), 'w') as f:
        json.dump(violations, f, indent=2)

    print(f"Cycle groups: {len(cycles['cycle_groups'])}")
    print(f"Layer violations: {violations['total_violations']}")
    print(f"Results written to {results_dir}/")


if __name__ == "__main__":
    main()
