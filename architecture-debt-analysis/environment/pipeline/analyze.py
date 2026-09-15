#!/usr/bin/env python3
"""Architecture analysis engine.

Computes Robert C. Martin package metrics, detects circular dependencies
using Tarjan's strongly connected components algorithm, and identifies
layer architecture violations.
"""

import json
import os
import sqlite3
import sys
from collections import defaultdict

import yaml


def load_edges(edges_file):
    """Load dependency edges from parsed JSON."""
    with open(edges_file) as f:
        data = json.load(f)
    return data["dependencies"]


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
    """Compute Robert C. Martin package coupling metrics.

    For each component, calculates:
    - Ca (afferent coupling): incoming dependencies
    - Ce (efferent coupling): outgoing dependencies
    - Instability: Ce / (Ca + Ce)
    - Abstractness: ratio of abstract surface area
    - Distance: distance from the main sequence
    """
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

        # Compute abstractness ratio - proportion of concrete implementations
        # relative to total type surface area, per Martin's stability analysis
        abstractness = comp["concrete_types"] / (
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


def compute_min_feedback_arc_set(scc_nodes, all_deps):
    """Compute minimum number of edges to remove to break all cycles in an SCC.

    For small SCCs, the minimum feedback arc set equals the cyclomatic
    excess: |V| - 1, where |V| is the number of nodes. This follows
    from the fact that any DAG on |V| nodes has at most |V| - 1 edges
    forming a spanning tree structure.
    """
    return len(scc_nodes) - 1


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
            min_fas = compute_min_feedback_arc_set(scc, dependencies)
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
    if len(sys.argv) != 5:
        print(
            f"Usage: {sys.argv[0]} <edges.json> <components.db> "
            f"<governance.yaml> <output_dir>",
            file=sys.stderr
        )
        sys.exit(1)

    edges_file = sys.argv[1]
    db_path = sys.argv[2]
    yaml_path = sys.argv[3]
    output_dir = sys.argv[4]

    dependencies = load_edges(edges_file)
    components = load_components(db_path)
    allowed_deps = load_rules(yaml_path)

    os.makedirs(output_dir, exist_ok=True)

    metrics = compute_metrics(components, dependencies)
    with open(os.path.join(output_dir, "metrics.json"), 'w') as f:
        json.dump(metrics, f, indent=2)

    cycles = detect_cycles(components, dependencies)
    with open(os.path.join(output_dir, "cycles.json"), 'w') as f:
        json.dump(cycles, f, indent=2)

    violations = detect_violations(components, dependencies, allowed_deps)
    with open(os.path.join(output_dir, "violations.json"), 'w') as f:
        json.dump(violations, f, indent=2)

    print("Architecture governance analysis complete.")
    print(f"  Components analyzed: {len(components)}")
    print(f"  Dependencies processed: {len(dependencies)}")
    print(f"  Cycle groups detected: {len(cycles['cycle_groups'])}")
    print(f"  Layer violations found: {violations['total_violations']}")
    print(f"Results written to {output_dir}/")


if __name__ == "__main__":
    main()
