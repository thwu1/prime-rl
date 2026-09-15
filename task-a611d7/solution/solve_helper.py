#!/usr/bin/env python3

"""
Correct dependency graph analyzer for the monorepo.
Handles both py_library and py_service macro BUILD file formats,
all Python import patterns, full graph analysis, and SVG visualization.
"""

import json
import os
import re
import subprocess
import networkx as nx

MONOREPO = "/app/monorepo"
OUTPUT = "/app/audit_report.json"
DOT_OUTPUT = "/app/dep_graph.dot"
SVG_OUTPUT = "/app/dep_graph.svg"


def parse_build_files():
    """Extract declared dependencies from all BUILD files.

    Handles both standard py_library (deps = ["//name", ...]) and
    py_service macro (service_deps = ["name", ...] bare names +
    internal_deps = ["//name", ...] labels).
    """
    all_packages = set()
    for entry in sorted(os.listdir(MONOREPO)):
        pkg_dir = os.path.join(MONOREPO, entry)
        if os.path.isdir(pkg_dir) and os.path.isfile(
            os.path.join(pkg_dir, "BUILD")
        ):
            all_packages.add(entry)

    declared = {}
    for pkg in sorted(all_packages):
        build_path = os.path.join(MONOREPO, pkg, "BUILD")
        with open(build_path) as f:
            content = f.read()

        deps = set()

        # Match standard "//name" label deps
        for m in re.finditer(r'"//(\w+)"', content):
            dep = m.group(1)
            if dep in all_packages:
                deps.add(dep)

        # Handle py_service macro: extract bare names from service_deps
        if "py_service(" in content:
            svc_match = re.search(
                r"service_deps\s*=\s*\[(.*?)\]", content, re.DOTALL
            )
            if svc_match:
                for m in re.finditer(r'"(\w+)"', svc_match.group(1)):
                    dep = m.group(1)
                    if dep in all_packages:
                        deps.add(dep)

        declared[pkg] = sorted(deps)
    return declared


def parse_source_imports():
    """Extract actual import dependencies from Python source files.

    Handles all import patterns including indented conditional imports
    inside try/except blocks.
    """
    packages = set()
    for entry in os.listdir(MONOREPO):
        pkg_dir = os.path.join(MONOREPO, entry)
        if os.path.isdir(pkg_dir) and os.path.isfile(
            os.path.join(pkg_dir, "BUILD")
        ):
            packages.add(entry)

    actual = {}
    for pkg in sorted(packages):
        module_path = os.path.join(MONOREPO, pkg, "module.py")
        if not os.path.isfile(module_path):
            actual[pkg] = []
            continue

        with open(module_path) as f:
            content = f.read()

        imports = set()
        # No ^ anchor: matches indented imports too
        for match in re.finditer(
            r"(?:from|import)\s+monorepo\.(\w+)", content
        ):
            dep = match.group(1)
            if dep in packages and dep != pkg:
                imports.add(dep)

        actual[pkg] = sorted(imports)

    return actual


def build_digraph(dep_dict):
    """Build a networkx DiGraph from a dependency dict."""
    G = nx.DiGraph()
    for pkg in dep_dict:
        G.add_node(pkg)
    for pkg, deps in dep_dict.items():
        for dep in deps:
            G.add_edge(pkg, dep)
    return G


def build_condensed_dag(G):
    """Condense SCCs into single nodes and return the DAG + label mapping."""
    scc_labels = {}
    for scc in nx.strongly_connected_components(G):
        label = "|".join(sorted(scc))
        for node in scc:
            scc_labels[node] = label

    condensed = nx.DiGraph()
    for node in G.nodes():
        condensed.add_node(scc_labels[node])
    for u, v in G.edges():
        src = scc_labels[u]
        dst = scc_labels[v]
        if src != dst:
            condensed.add_edge(src, dst)

    return condensed, scc_labels


def compute_build_layers(condensed):
    """Compute parallel build layers via topological depth assignment."""
    memo = {}

    def depth(node):
        if node in memo:
            return memo[node]
        successors = list(condensed.successors(node))
        if not successors:
            memo[node] = 0
            return 0
        d = max(depth(s) for s in successors) + 1
        memo[node] = d
        return d

    for node in condensed.nodes():
        depth(node)

    if not memo:
        return []

    max_layer = max(memo.values())
    layers = [[] for _ in range(max_layer + 1)]
    for node, layer in memo.items():
        layers[layer].append(node)

    return layers


def generate_dot(declared):
    """Generate DOT format graph for graphviz rendering."""
    lines = ["digraph dependencies {"]
    lines.append("    rankdir=BT;")
    lines.append('    node [shape=box, style=filled, fillcolor="#ffffcc"];')
    lines.append("")

    for pkg in sorted(declared):
        lines.append(f'    "{pkg}";')

    lines.append("")

    for pkg in sorted(declared):
        for dep in declared[pkg]:
            lines.append(f'    "{pkg}" -> "{dep}";')

    lines.append("}")
    return "\n".join(lines)


def main():
    declared = parse_build_files()
    actual = parse_source_imports()

    G_declared = build_digraph(declared)

    # Basic counts
    node_count = G_declared.number_of_nodes()
    declared_edge_count = G_declared.number_of_edges()
    actual_edge_count = sum(len(deps) for deps in actual.values())

    # Cycles (SCCs with > 1 node)
    cycles = []
    for scc in nx.strongly_connected_components(G_declared):
        if len(scc) > 1:
            cycles.append(sorted(scc))
    cycles.sort()

    # Stale and missing deps
    stale_deps = []
    for pkg in sorted(declared):
        for dep in declared[pkg]:
            if dep not in actual.get(pkg, []):
                stale_deps.append([pkg, dep])
    stale_deps.sort()

    missing_deps = []
    for pkg in sorted(actual):
        for dep in actual[pkg]:
            if dep not in declared.get(pkg, []):
                missing_deps.append([pkg, dep])
    missing_deps.sort()

    # Articulation points and bridges (undirected graph)
    G_undirected = G_declared.to_undirected()
    articulation_points = sorted(nx.articulation_points(G_undirected))
    bridges = [sorted([u, v]) for u, v in nx.bridges(G_undirected)]
    bridges.sort()

    # Condensed DAG
    condensed, scc_labels = build_condensed_dag(G_declared)

    # Build schedule (parallel layers)
    condensed_layers = compute_build_layers(condensed)
    build_schedule = []
    for layer_nodes in condensed_layers:
        pkg_layer = []
        for label in sorted(layer_nodes):
            pkg_layer.extend(sorted(label.split("|")))
        build_schedule.append(sorted(pkg_layer))

    # Critical path length
    critical_path_length = nx.dag_longest_path_length(condensed)

    # Transitive reduction
    tr = nx.transitive_reduction(condensed)
    transitive_reduction_removed = []
    for pkg, deps in declared.items():
        for dep in deps:
            src = scc_labels[pkg]
            dst = scc_labels[dep]
            if src != dst and not tr.has_edge(src, dst):
                transitive_reduction_removed.append([pkg, dep])
    transitive_reduction_removed.sort()

    # Generate visualization
    dot_content = generate_dot(declared)
    with open(DOT_OUTPUT, "w") as f:
        f.write(dot_content)
    subprocess.run(
        ["dot", "-Tsvg", DOT_OUTPUT, "-o", SVG_OUTPUT],
        check=True,
    )

    # Write report
    report = {
        "node_count": node_count,
        "declared_edge_count": declared_edge_count,
        "actual_edge_count": actual_edge_count,
        "cycles": cycles,
        "stale_deps": stale_deps,
        "missing_deps": missing_deps,
        "articulation_points": articulation_points,
        "bridges": bridges,
        "build_schedule": build_schedule,
        "critical_path_length": critical_path_length,
        "transitive_reduction_removed": transitive_reduction_removed,
    }

    with open(OUTPUT, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Analysis report written to {OUTPUT}")
    print(f"Dependency graph written to {SVG_OUTPUT}")
    print(f"  Nodes: {node_count}")
    print(f"  Declared edges: {declared_edge_count}")
    print(f"  Actual edges: {actual_edge_count}")
    print(f"  Cycles: {len(cycles)}")
    print(f"  Stale deps: {len(stale_deps)}")
    print(f"  Missing deps: {len(missing_deps)}")
    print(f"  Articulation points: {len(articulation_points)}")
    print(f"  Bridges: {len(bridges)}")
    print(f"  Build layers: {len(build_schedule)}")
    print(f"  Critical path: {critical_path_length}")
    print(
        f"  Transitive reduction removed: "
        f"{len(transitive_reduction_removed)}"
    )


if __name__ == "__main__":
    main()
