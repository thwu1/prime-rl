#!/usr/bin/env python3
"""Feature dependency analysis pipeline.

Multi-stage analysis: extract → resolve → graph → store → analyze.
Orchestrated by Makefile, produces JSON, DOT, SVG, and SQLite outputs.
"""

import ast
import json
import os
import sqlite3
import sys
from collections import defaultdict
from itertools import combinations


# ── Helpers ─────────────────────────────────────────────────────


def find_source_modules(codebase_dir):
    """Find source modules (exclude __init__.py, conftest.py, test files)."""
    modules = []
    for root, dirs, files in os.walk(codebase_dir):
        for f in files:
            if not f.endswith(".py"):
                continue
            if f == "__init__.py" or f == "conftest.py":
                continue
            if f.startswith("test_") or f.endswith("_test.py"):
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, codebase_dir).replace(os.sep, "/")
            modules.append(rel)
    return sorted(modules)


def find_test_files(codebase_dir):
    """Find test files."""
    tests = []
    for root, dirs, files in os.walk(codebase_dir):
        for f in files:
            if f.endswith(".py") and (
                f.startswith("test_") or f.endswith("_test.py")
            ):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, codebase_dir).replace(os.sep, "/")
                tests.append(rel)
    return sorted(tests)


# ── Stage 1: Extract ────────────────────────────────────────────


def cmd_extract(codebase_dir, output_path):
    """Parse source modules via AST, extract import records."""
    source_modules = find_source_modules(codebase_dir)
    result = {}

    for mod_path in source_modules:
        full_path = os.path.join(codebase_dir, mod_path)
        with open(full_path) as f:
            source = f.read()

        tree = ast.parse(source, full_path)

        # Mark nodes inside try/except as conditional
        conditional_ids = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for child in ast.walk(node):
                    if isinstance(child, (ast.Import, ast.ImportFrom)):
                        conditional_ids.add(id(child))

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imp_type = (
                        "conditional" if id(node) in conditional_ids else "absolute"
                    )
                    imports.append({
                        "module": alias.name,
                        "names": [alias.asname or alias.name],
                        "line": node.lineno,
                        "type": imp_type,
                    })
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                level = node.level or 0
                if id(node) in conditional_ids:
                    imp_type = "conditional"
                elif level > 0:
                    imp_type = "relative"
                else:
                    imp_type = "absolute"

                module_str = ("." * level + node.module) if level > 0 else node.module
                names = [alias.name for alias in node.names]
                imports.append({
                    "module": module_str,
                    "names": names,
                    "line": node.lineno,
                    "type": imp_type,
                })

        result[mod_path] = imports

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, sort_keys=True)


# ── Stage 2: Resolve ────────────────────────────────────────────


def cmd_resolve(codebase_dir, raw_path, output_path):
    """Resolve raw imports to source file paths."""
    with open(raw_path) as f:
        raw = json.load(f)

    source_set = set(find_source_modules(codebase_dir))
    result = {}

    for mod_path, imports in raw.items():
        deps = set()
        for imp in imports:
            module = imp["module"]
            imp_type = imp["type"]

            if imp_type == "relative" or module.startswith("."):
                # Relative import: resolve against package directory
                dots = 0
                rest = module
                while rest.startswith("."):
                    dots += 1
                    rest = rest[1:]

                pkg = os.path.dirname(mod_path)
                for _ in range(dots - 1):
                    pkg = os.path.dirname(pkg)

                if rest:
                    target = os.path.join(pkg, rest.replace(".", "/"))
                else:
                    target = pkg

                target_py = target.replace(os.sep, "/") + ".py"
                if target_py in source_set:
                    deps.add(target_py)
            else:
                # Absolute import
                parts = module.split(".")
                target_py = "/".join(parts) + ".py"
                if target_py in source_set:
                    deps.add(target_py)

        result[mod_path] = sorted(deps)

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, sort_keys=True)


# ── Stage 3: Graph ──────────────────────────────────────────────


def cmd_graph(resolved_path, dot_path):
    """Generate Graphviz DOT with subgraph clusters per package."""
    with open(resolved_path) as f:
        graph = json.load(f)

    packages = defaultdict(list)
    for mod in graph:
        pkg = mod.split("/")[0]
        packages[pkg].append(mod)

    lines = ["digraph dependencies {", "    rankdir=LR;", "    node [shape=box];", ""]

    for pkg in sorted(packages):
        lines.append(f"    subgraph cluster_{pkg} {{")
        lines.append(f'        label="{pkg}";')
        for mod in sorted(packages[pkg]):
            node_id = mod.replace("/", "_").replace(".", "_")
            lines.append(f'        "{node_id}" [label="{mod}"];')
        lines.append("    }")
        lines.append("")

    for src, deps in sorted(graph.items()):
        src_id = src.replace("/", "_").replace(".", "_")
        for dep in deps:
            dep_id = dep.replace("/", "_").replace(".", "_")
            lines.append(f'    "{src_id}" -> "{dep_id}";')

    lines.append("}")

    with open(dot_path, "w") as f:
        f.write("\n".join(lines) + "\n")


# ── Stage 4: Store ──────────────────────────────────────────────


def cmd_store(codebase_dir, resolved_path, db_path):
    """Create and populate SQLite database with normalized schema."""
    with open(resolved_path) as f:
        graph = json.load(f)

    raw_path = os.path.join(os.path.dirname(resolved_path), "raw_imports.json")
    with open(raw_path) as f:
        raw = json.load(f)

    if os.path.exists(db_path):
        os.remove(db_path)

    db = sqlite3.connect(db_path)
    c = db.cursor()

    # Create schema
    c.execute("""CREATE TABLE modules (
        id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, package TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE dependencies (
        source_id INTEGER REFERENCES modules(id),
        target_id INTEGER REFERENCES modules(id),
        import_type TEXT NOT NULL,
        PRIMARY KEY(source_id, target_id)
    )""")
    c.execute("""CREATE TABLE test_cones (
        test_path TEXT NOT NULL,
        module_id INTEGER REFERENCES modules(id),
        PRIMARY KEY(test_path, module_id)
    )""")
    c.execute("""CREATE TABLE features (
        feature_id INTEGER NOT NULL,
        module_id INTEGER REFERENCES modules(id),
        PRIMARY KEY(feature_id, module_id)
    )""")
    c.execute("""CREATE TABLE feature_tests (
        feature_id INTEGER NOT NULL,
        test_path TEXT NOT NULL,
        PRIMARY KEY(feature_id, test_path)
    )""")

    # Insert modules
    mod_ids = {}
    for i, mod_path in enumerate(sorted(graph.keys())):
        pkg = mod_path.split("/")[0]
        c.execute(
            "INSERT INTO modules (id, path, package) VALUES (?, ?, ?)",
            (i, mod_path, pkg),
        )
        mod_ids[mod_path] = i

    # Insert dependencies with import type
    for src, deps in graph.items():
        src_imports = raw.get(src, [])
        for dep in deps:
            imp_type = _find_import_type(src, dep, src_imports)
            if src in mod_ids and dep in mod_ids:
                c.execute(
                    "INSERT OR IGNORE INTO dependencies VALUES (?, ?, ?)",
                    (mod_ids[src], mod_ids[dep], imp_type),
                )

    # Compute test cones and features for DB
    test_files = find_test_files(codebase_dir)
    test_cones = _compute_test_cones(codebase_dir, graph, test_files)
    features = _compute_features(test_cones)

    # Insert test cones
    for test, cone in test_cones.items():
        for mod in cone:
            if mod in mod_ids:
                c.execute(
                    "INSERT INTO test_cones VALUES (?, ?)", (test, mod_ids[mod])
                )

    # Insert features
    for feat in features:
        for mod in feat["source_files"]:
            if mod in mod_ids:
                c.execute(
                    "INSERT INTO features VALUES (?, ?)",
                    (feat["id"], mod_ids[mod]),
                )
        for test in feat["tests"]:
            c.execute(
                "INSERT INTO feature_tests VALUES (?, ?)", (feat["id"], test)
            )

    db.commit()
    db.close()


def _find_import_type(src, dep, src_imports):
    """Determine the import type for a resolved dependency."""
    for imp in src_imports:
        module = imp["module"]
        if imp["type"] in ("relative", "conditional"):
            dots = sum(1 for ch in module if ch == ".")
            rest = module.lstrip(".")
            pkg = os.path.dirname(src)
            for _ in range(dots - 1):
                pkg = os.path.dirname(pkg)
            if rest:
                target = os.path.join(pkg, rest.replace(".", "/")) + ".py"
            else:
                target = pkg + ".py"
            target = target.replace(os.sep, "/")
            if target == dep:
                return imp["type"]
        else:
            parts = module.split(".")
            target = "/".join(parts) + ".py"
            if target == dep:
                return imp["type"]
    return "absolute"


# ── Stage 5: Analyze ────────────────────────────────────────────


def cmd_analyze(codebase_dir, resolved_path, output_path):
    """Produce final analysis JSON."""
    with open(resolved_path) as f:
        graph = json.load(f)

    test_files = find_test_files(codebase_dir)
    test_cones = _compute_test_cones(codebase_dir, graph, test_files)
    features = _compute_features(test_cones)
    isolation = _compute_isolation_matrix(features)
    mds = _compute_mds(features, test_cones)

    result = {
        "dependency_graph": graph,
        "test_dependency_cones": test_cones,
        "features": features,
        "isolation_matrix": isolation,
        "minimal_disruption_sets": mds,
    }

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, sort_keys=True)


# ── Shared Analysis Logic ───────────────────────────────────────


def _compute_test_cones(codebase_dir, graph, test_files):
    """Compute transitive dependency cones for test files."""
    source_set = set(graph.keys())
    cones = {}

    for test in test_files:
        full_path = os.path.join(codebase_dir, test)
        if not os.path.exists(full_path):
            continue

        with open(full_path) as f:
            source = f.read()

        tree = ast.parse(source, full_path)
        direct_deps = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                level = node.level or 0
                if level > 0:
                    pkg = os.path.dirname(test)
                    rest = node.module
                    for _ in range(level - 1):
                        pkg = os.path.dirname(pkg)
                    if rest:
                        target = (
                            os.path.join(pkg, rest.replace(".", "/")) + ".py"
                        )
                    else:
                        target = pkg + ".py"
                    target = target.replace(os.sep, "/")
                else:
                    parts = node.module.split(".")
                    target = "/".join(parts) + ".py"
                if target in source_set:
                    direct_deps.add(target)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    target = "/".join(parts) + ".py"
                    if target in source_set:
                        direct_deps.add(target)

        # Transitive closure via BFS
        visited = set()
        stack = list(direct_deps)
        while stack:
            mod = stack.pop()
            if mod in visited:
                continue
            visited.add(mod)
            for dep in graph.get(mod, []):
                if dep not in visited:
                    stack.append(dep)

        cones[test] = sorted(visited)

    return cones


def _compute_features(test_cones):
    """Cluster tests into features via Union-Find."""
    tests = sorted(test_cones.keys())
    if not tests:
        return []

    parent = {t: t for t in tests}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    for i in range(len(tests)):
        for j in range(i + 1, len(tests)):
            if set(test_cones[tests[i]]) & set(test_cones[tests[j]]):
                union(tests[i], tests[j])

    groups = defaultdict(list)
    for t in tests:
        groups[find(t)].append(t)

    features = []
    for group_tests in sorted(groups.values(), key=lambda g: min(g)):
        source_files = set()
        for t in group_tests:
            source_files.update(test_cones[t])
        features.append({
            "id": len(features),
            "tests": sorted(group_tests),
            "source_files": sorted(source_files),
        })

    return features


def _compute_isolation_matrix(features):
    """Compute Jaccard similarity matrix."""
    n = len(features)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        si = set(features[i]["source_files"])
        for j in range(n):
            sj = set(features[j]["source_files"])
            if i == j:
                matrix[i][j] = 1.0
            else:
                union_size = len(si | sj)
                matrix[i][j] = len(si & sj) / union_size if union_size else 0.0
    return matrix


def _compute_mds(features, test_cones):
    """Compute minimal disruption sets with exclusion constraints."""
    result = {}

    for feat in features:
        fid = str(feat["id"])
        feat_tests = feat["tests"]
        feat_cones = {t: set(test_cones[t]) for t in feat_tests}

        # Other features' combined cone
        other_cone_files = set()
        for other in features:
            if other["id"] != feat["id"]:
                for t in other["tests"]:
                    other_cone_files.update(test_cones[t])

        # Candidates: only files exclusive to this feature
        candidates = sorted(
            f for f in feat["source_files"] if f not in other_cone_files
        )

        # Brute-force minimum hitting set
        best = None
        for size in range(1, len(candidates) + 1):
            for combo in combinations(candidates, size):
                combo_set = set(combo)
                if all(combo_set & cone for cone in feat_cones.values()):
                    candidate = sorted(combo)
                    if best is None or candidate < best:
                        best = candidate
            if best is not None:
                break

        result[fid] = best if best else []

    return result


# ── CLI Dispatch ────────────────────────────────────────────────


if __name__ == "__main__":
    cmd = sys.argv[1]

    if cmd == "extract":
        cmd_extract(sys.argv[2], sys.argv[3])
    elif cmd == "resolve":
        cmd_resolve(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "graph":
        cmd_graph(sys.argv[2], sys.argv[3])
    elif cmd == "store":
        cmd_store(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "analyze":
        cmd_analyze(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
