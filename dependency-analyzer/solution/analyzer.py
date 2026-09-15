#!/usr/bin/env python3
"""Feature Dependency Analyzer for Python codebases.

Analyzes import dependencies, computes transitive test cones,
clusters tests into features, computes isolation metrics,
and determines minimal disruption sets.
"""

import ast
import json
import os
import sys
from collections import defaultdict
from itertools import combinations


def find_python_files(root):
    files = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith(".py") and fn != "__init__.py":
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root)
                files.append(rel.replace(os.sep, "/"))
    return sorted(files)


def is_test_file(filepath):
    basename = os.path.basename(filepath)
    return basename.startswith("test_") or basename.endswith("_test.py")


def resolve_import(module_name, codebase_root):
    parts = module_name.split(".")
    path = os.path.join(codebase_root, *parts) + ".py"
    if os.path.exists(path):
        rel = os.path.relpath(path, codebase_root).replace(os.sep, "/")
        if os.path.basename(rel) == "__init__.py":
            return None
        return rel
    pkg_init = os.path.join(codebase_root, *parts, "__init__.py")
    if os.path.exists(pkg_init):
        return None
    return None


def extract_imports(filepath, codebase_root):
    full_path = os.path.join(codebase_root, filepath)
    try:
        with open(full_path) as f:
            tree = ast.parse(f.read())
    except (SyntaxError, UnicodeDecodeError):
        return []

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolved = resolve_import(alias.name, codebase_root)
                if resolved:
                    imports.add(resolved)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                resolved = resolve_import(node.module, codebase_root)
                if resolved:
                    imports.add(resolved)
                else:
                    for alias in node.names:
                        full_module = f"{node.module}.{alias.name}"
                        resolved = resolve_import(full_module, codebase_root)
                        if resolved:
                            imports.add(resolved)
    return sorted(imports)


def build_dependency_graph(source_files, codebase_root):
    source_set = set(source_files)
    graph = {}
    for f in source_files:
        deps = extract_imports(f, codebase_root)
        graph[f] = sorted(d for d in deps if d in source_set and d != f)
    return graph


def compute_transitive_closure(start_files, graph):
    visited = set()
    stack = list(start_files)
    while stack:
        f = stack.pop()
        if f in visited:
            continue
        visited.add(f)
        for dep in graph.get(f, []):
            if dep not in visited:
                stack.append(dep)
    return sorted(visited)


def compute_test_cones(test_files, source_files, graph, codebase_root):
    source_set = set(source_files)
    cones = {}
    for test in test_files:
        direct_deps = extract_imports(test, codebase_root)
        source_deps = [d for d in direct_deps if d in source_set]
        cone = compute_transitive_closure(source_deps, graph)
        cones[test] = cone
    return cones


def cluster_features(test_cones):
    tests = sorted(test_cones.keys())
    if not tests:
        return []

    parent = {t: t for t in tests}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            if px < py:
                parent[py] = px
            else:
                parent[px] = py

    for i in range(len(tests)):
        for j in range(i + 1, len(tests)):
            cone_i = set(test_cones[tests[i]])
            cone_j = set(test_cones[tests[j]])
            if cone_i & cone_j:
                union(tests[i], tests[j])

    components = defaultdict(list)
    for t in tests:
        components[find(t)].append(t)

    sorted_components = sorted(components.values(), key=lambda c: min(c))

    features = []
    for fid, component in enumerate(sorted_components):
        tests_in_feature = sorted(component)
        source_files_set = sorted(
            set(f for t in tests_in_feature for f in test_cones[t])
        )
        features.append({
            "id": fid,
            "tests": tests_in_feature,
            "source_files": source_files_set,
        })
    return features


def compute_isolation_matrix(features):
    n = len(features)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            si = set(features[i]["source_files"])
            sj = set(features[j]["source_files"])
            union_size = len(si | sj)
            if union_size == 0:
                matrix[i][j] = 1.0 if i == j else 0.0
            else:
                matrix[i][j] = len(si & sj) / union_size
    return matrix


def compute_minimal_disruption_sets(features, test_cones):
    result = {}

    for feature in features:
        fid = feature["id"]
        target_tests = feature["tests"]

        other_cone_files = set()
        for other in features:
            if other["id"] == fid:
                continue
            for t in other["tests"]:
                other_cone_files.update(test_cones[t])

        allowed = set(feature["source_files"]) - other_cone_files

        restricted_cones = []
        for t in target_tests:
            rc = set(test_cones[t]) & allowed
            restricted_cones.append(rc)

        allowed_list = sorted(allowed)
        best = None
        for size in range(1, len(allowed_list) + 1):
            for subset in combinations(allowed_list, size):
                subset_set = set(subset)
                if all(subset_set & rc for rc in restricted_cones):
                    candidate = sorted(subset)
                    if best is None or candidate < best:
                        best = candidate
            if best is not None:
                break

        result[str(fid)] = best if best else []

    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: analyzer.py <codebase_path>", file=sys.stderr)
        sys.exit(1)

    codebase_root = os.path.abspath(sys.argv[1])
    output_path = "/app/output/analysis.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    all_files = find_python_files(codebase_root)
    source_files = sorted(f for f in all_files if not is_test_file(f))
    test_files = sorted(f for f in all_files if is_test_file(f))

    graph = build_dependency_graph(source_files, codebase_root)
    test_cones = compute_test_cones(test_files, source_files, graph, codebase_root)
    features = cluster_features(test_cones)
    isolation_matrix = compute_isolation_matrix(features)
    mds = compute_minimal_disruption_sets(features, test_cones)

    output = {
        "dependency_graph": graph,
        "test_dependency_cones": test_cones,
        "features": features,
        "isolation_matrix": isolation_matrix,
        "minimal_disruption_sets": mds,
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    main()
