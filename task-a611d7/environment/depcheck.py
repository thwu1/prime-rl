#!/usr/bin/env python3
"""
Multi-tool dependency health auditor for the monorepo.

Pipeline stages:
1. buildozer  -> extract declared deps from BUILD file metadata
2. Python regex -> parse actual imports from source files
3. Python algorithms -> analyze dependency graph structure
4. graphviz  -> render dependency visualization

Usage: python3 depcheck.py

Output:
  /app/audit_report.json  -- structured health report
  /app/dep_graph.svg      -- dependency graph visualization

Required tools: buildozer, dot (graphviz)
"""

import json
import os
import re
import subprocess
import sys

MONOREPO = "/app/monorepo"
OUTPUT = "/app/audit_report.json"
SVG_OUTPUT = "/app/dep_graph.svg"
DOT_OUTPUT = "/app/dep_graph.dot"

# Expected report schema -- all keys must be present in the output
REPORT_SCHEMA = {
    "node_count": "int: number of packages",
    "declared_edge_count": "int: total declared dependency edges across all BUILD files",
    "actual_edge_count": "int: total import-based dependency edges across all source files",
    "cycles": "list of lists: strongly connected components with more than one node; each SCC is a sorted list of package names; outer list sorted",
    "stale_deps": "sorted list of [source, target]: dependencies declared in BUILD but absent from source imports",
    "missing_deps": "sorted list of [source, target]: dependencies present in source imports but absent from BUILD",
    "articulation_points": "sorted list: cut vertices in the undirected projection of the declared dependency graph",
    "bridges": "sorted list of sorted [u, v] pairs: bridge edges in the undirected projection",
    "build_schedule": "list of lists: parallel build layers from topological sort of the condensed DAG (cycles collapsed); each layer is a sorted list of original package names, ordered from leaf packages (no dependencies) to root packages",
    "critical_path_length": "int: longest path length in edges in the condensed DAG",
    "transitive_reduction_removed": "sorted list of [source, target]: declared dependency edges that are transitively redundant in the condensed DAG, mapped back to original package names",
}


def discover_packages():
    """Find all package directories that have BUILD files."""
    packages = set()
    for entry in sorted(os.listdir(MONOREPO)):
        pkg_dir = os.path.join(MONOREPO, entry)
        if os.path.isdir(pkg_dir) and os.path.isfile(
            os.path.join(pkg_dir, "BUILD")
        ):
            packages.add(entry)
    return packages


def buildozer_print(build_path, target_name, attribute):
    """Query a single attribute from a BUILD target using buildozer.

    Returns the stdout string (stripped). On success, the output is the
    attribute value; for missing attributes buildozer prints '(missing)'.
    """
    result = subprocess.run(
        ["buildozer", f"print {attribute}", f"{build_path}:{target_name}"],
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def parse_label_list(raw, all_packages):
    """Parse a buildozer list output into a set of package names.

    Handles both '//name' labels and bare 'name' strings.
    buildozer outputs lists as: [elem1 elem2 ...] or []
    A missing attribute outputs: (missing)
    """
    if not raw or raw == "[]" or raw == "(missing)":
        return set()

    inner = raw.strip("[]").strip()
    if not inner:
        return set()

    names = set()
    for token in inner.split():
        token = token.strip('"').strip("'")
        # Strip leading slashes for //name format
        name = token.lstrip("/")
        if name in all_packages:
            names.add(name)
    return names


def extract_declared_deps(packages):
    """Extract declared dependencies from all BUILD files using buildozer.

    Queries the 'deps' attribute of each package's primary target.
    """
    declared = {}
    for pkg in sorted(packages):
        build_path = os.path.join(MONOREPO, pkg, "BUILD")

        # Query the standard 'deps' attribute
        output = buildozer_print(build_path, pkg, "deps")
        deps = parse_label_list(output, packages)

        declared[pkg] = sorted(deps)

    return declared


def parse_source_imports(pkg, all_packages):
    """Parse actual import dependencies from a package's Python source."""
    module_path = os.path.join(MONOREPO, pkg, "module.py")
    if not os.path.isfile(module_path):
        return []

    with open(module_path) as f:
        content = f.read()

    imports = set()
    for match in re.finditer(
        r"^(?:from|import)\s+monorepo\.(\w+)", content, re.MULTILINE
    ):
        dep = match.group(1)
        if dep in all_packages and dep != pkg:
            imports.add(dep)

    return sorted(imports)


def find_sccs(graph):
    """Find strongly connected components using Tarjan's algorithm."""
    index_counter = [0]
    stack = []
    lowlinks = {}
    index = {}
    on_stack = {}
    result = []

    def strongconnect(v):
        index[v] = index_counter[0]
        lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True

        for w in graph.get(v, []):
            if w not in index:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif on_stack.get(w, False):
                lowlinks[v] = min(lowlinks[v], index[w])

        if lowlinks[v] == index[v]:
            scc = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == v:
                    break
            result.append(sorted(scc))

    for v in sorted(graph.keys()):
        if v not in index:
            strongconnect(v)

    return sorted(result)


def generate_visualization(declared):
    """Generate DOT graph and render to SVG using graphviz."""
    # TODO: Not yet implemented
    pass


def main():
    packages = discover_packages()

    # Stage 1: Extract declared deps via buildozer
    print("Stage 1: Extracting declared deps via buildozer...")
    declared = extract_declared_deps(packages)

    # Stage 2: Parse source imports
    print("Stage 2: Parsing source imports...")
    actual = {}
    for pkg in sorted(packages):
        actual[pkg] = parse_source_imports(pkg, packages)

    node_count = len(packages)
    declared_edge_count = sum(len(d) for d in declared.values())
    actual_edge_count = sum(len(d) for d in actual.values())

    # Stage 3: Graph analysis
    print("Stage 3: Analyzing dependency graph...")

    all_sccs = find_sccs(declared)
    cycles = [scc for scc in all_sccs if len(scc) >= 1]

    stale_deps = []
    for pkg in sorted(packages):
        for dep in declared[pkg]:
            if dep not in actual.get(pkg, []):
                stale_deps.append([pkg, dep])
    stale_deps.sort()

    missing_deps = []
    for pkg in sorted(packages):
        for dep in actual[pkg]:
            if dep not in declared.get(pkg, []):
                missing_deps.append([pkg, dep])
    missing_deps.sort()

    # TODO: articulation_points -- not yet implemented
    articulation_points = []

    # TODO: bridges -- not yet implemented
    bridges = []

    # TODO: build_schedule -- not yet implemented
    build_schedule = []

    # TODO: critical_path_length -- not yet implemented
    critical_path_length = 0

    # TODO: transitive_reduction_removed -- not yet implemented
    transitive_reduction_removed = []

    # Stage 4: Visualization
    print("Stage 4: Generating dependency visualization...")
    generate_visualization(declared)

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

    print(f"\nReport written to {OUTPUT}")
    for key, value in report.items():
        if isinstance(value, list):
            print(f"  {key}: {len(value)} items")
        else:
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
