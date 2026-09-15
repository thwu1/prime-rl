#!/usr/bin/env python3

"""Dependency ratchet analyzer with coupling metrics, FAS computation,
SQLite database, and Graphviz visualization."""

import json
import os
import re
import sqlite3
import subprocess
from collections import defaultdict, deque
from itertools import combinations

import yaml


# ── Parsing ─────────────────────────────────────────────────────


def load_layers(path):
    with open(path) as f:
        data = yaml.safe_load(f)
    return {layer["name"]: layer["index"] for layer in data["layers"]}


def camel_to_snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def parse_package(pkg_dir):
    with open(os.path.join(pkg_dir, "package.rb")) as f:
        content = f.read()
    name = os.path.basename(pkg_dir)
    m = re.search(r"layer\s+'(\w+)'", content)
    layer = m.group(1) if m else None
    m = re.search(r"strict_dependencies\s+'(\w+)'", content)
    strict_deps = m.group(1) if m else "false"
    imports = [camel_to_snake(c) for c in re.findall(r"import\s+(\w+)", content)]
    return {"name": name, "layer": layer, "strict_dependencies": strict_deps,
            "imports": imports}


# ── Graph Algorithms ────────────────────────────────────────────

LEVEL_ORDER = ["false", "layered", "layered_dag", "dag"]


def find_sccs(adj, nodes):
    """Tarjan's algorithm. Returns list of SCCs (each a set) with size > 1."""
    idx = [0]
    stack, on_stack = [], set()
    index_of, lowlink = {}, {}
    sccs = []

    def connect(v):
        index_of[v] = lowlink[v] = idx[0]
        idx[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in adj.get(v, []):
            if w not in nodes:
                continue
            if w not in index_of:
                connect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index_of[w])
        if lowlink[v] == index_of[v]:
            scc = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                scc.append(w)
                if w == v:
                    break
            if len(scc) > 1:
                sccs.append(set(scc))

    for n in sorted(nodes):
        if n not in index_of:
            connect(n)
    return sccs


def nodes_in_cycles(adj, nodes):
    sccs = find_sccs(adj, nodes)
    return {n for scc in sccs for n in scc}, sccs


def bfs_distances(adj, source, all_nodes):
    """BFS from source. Returns dict of {target: shortest_distance} excluding self."""
    distances = {}
    visited = {source}
    queue = deque()
    for nb in adj.get(source, []):
        if nb in all_nodes and nb not in visited:
            visited.add(nb)
            distances[nb] = 1
            queue.append(nb)
    while queue:
        node = queue.popleft()
        d = distances[node]
        for nb in adj.get(node, []):
            if nb in all_nodes and nb not in visited:
                visited.add(nb)
                distances[nb] = d + 1
                queue.append(nb)
    return distances


def has_cycle_dfs(adj, nodes):
    """Return True if the directed subgraph induced by nodes has a cycle."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}

    def dfs(u):
        color[u] = GRAY
        for v in adj.get(u, []):
            if v not in nodes:
                continue
            if color[v] == GRAY:
                return True
            if color[v] == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    return any(color[n] == WHITE and dfs(n) for n in nodes)


def compute_min_fas(adj, scc_members):
    """Compute minimum feedback arc set for an SCC by enumeration.

    For small SCCs this is tractable. We enumerate edge subsets of
    increasing size until we find one whose removal makes the subgraph acyclic.
    """
    # Collect edges within the SCC
    edges = []
    for s in scc_members:
        for t in adj.get(s, []):
            if t in scc_members:
                edges.append((s, t))

    # Try removing k edges, starting from k=1
    for k in range(1, len(edges) + 1):
        for combo in combinations(range(len(edges)), k):
            remove_set = {edges[i] for i in combo}
            # Build reduced adjacency
            reduced = defaultdict(list)
            for s, t in edges:
                if (s, t) not in remove_set:
                    reduced[s].append(t)
            if not has_cycle_dfs(reduced, scc_members):
                return [list(edges[i]) for i in combo]

    return []  # Should never reach here for a valid SCC


# ── Violation Checking ──────────────────────────────────────────


def check_violations(pkg, packages, adj, layer_index_unused):
    level_idx = LEVEL_ORDER.index(pkg["strict_dependencies"])
    violations = []

    if level_idx >= 1:  # layered
        for imp in pkg["imports"]:
            if imp in packages:
                imp_li = packages[imp]["layer_index"]
                if imp_li > pkg["layer_index"]:
                    violations.append({
                        "type": "layering",
                        "description": (
                            f"imports '{imp}' from layer "
                            f"'{packages[imp]['layer']}' (index {imp_li}) "
                            f"which is above '{pkg['layer']}' "
                            f"(index {pkg['layer_index']})"
                        ),
                        "imported_package": imp,
                    })

    if level_idx >= 2:  # layered_dag
        same_layer = {n for n, p in packages.items()
                      if p["layer_index"] == pkg["layer_index"]}
        cyclic, sccs = nodes_in_cycles(adj, same_layer)
        if pkg["name"] in cyclic:
            for scc in sccs:
                if pkg["name"] in scc:
                    violations.append({
                        "type": "same_layer_cycle",
                        "description": (
                            f"participates in dependency cycle within "
                            f"layer '{pkg['layer']}': "
                            f"{' -> '.join(sorted(scc))}"
                        ),
                        "cycle": sorted(scc),
                    })
                    break

    if level_idx >= 3:  # dag
        all_nodes = set(packages.keys())
        cyclic, sccs = nodes_in_cycles(adj, all_nodes)
        if pkg["name"] in cyclic:
            for scc in sccs:
                if pkg["name"] in scc:
                    violations.append({
                        "type": "global_cycle",
                        "description": (
                            f"participates in dependency cycle in full "
                            f"graph: {' -> '.join(sorted(scc))}"
                        ),
                        "cycle": sorted(scc),
                    })
                    break

    return violations


def check_would_violate(pkg, packages, adj, next_level_idx):
    if next_level_idx >= 1:
        for imp in pkg["imports"]:
            if imp in packages and packages[imp]["layer_index"] > pkg["layer_index"]:
                return True
    if next_level_idx >= 2:
        same_layer = {n for n, p in packages.items()
                      if p["layer_index"] == pkg["layer_index"]}
        cyclic, _ = nodes_in_cycles(adj, same_layer)
        if pkg["name"] in cyclic:
            return True
    if next_level_idx >= 3:
        cyclic, _ = nodes_in_cycles(adj, set(packages.keys()))
        if pkg["name"] in cyclic:
            return True
    return False


# ── Coupling Metrics ───────────────────────────────────────────


def compute_coupling(packages, adj):
    """Compute afferent coupling, efferent coupling, and instability."""
    all_names = set(packages.keys())

    # Efferent: number of packages this one imports
    efferent = {}
    for name in all_names:
        efferent[name] = len([t for t in adj.get(name, []) if t in all_names])

    # Afferent: number of packages that import this one
    afferent = defaultdict(int)
    for name in all_names:
        for target in adj.get(name, []):
            if target in all_names:
                afferent[target] += 1

    metrics = {}
    for name in all_names:
        ca = afferent.get(name, 0)
        ce = efferent[name]
        total = ca + ce
        instability = round(ce / total, 4) if total > 0 else 0.0
        metrics[name] = {
            "afferent_coupling": ca,
            "efferent_coupling": ce,
            "instability": instability,
        }
    return metrics


# ── SQLite Database ─────────────────────────────────────────────


def create_database(db_path, packages, adj, all_distances, violations_data,
                    coupling_metrics):
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE packages (
        name TEXT PRIMARY KEY,
        layer TEXT NOT NULL,
        layer_index INTEGER NOT NULL,
        strict_dependencies TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE dependencies (
        source TEXT NOT NULL,
        target TEXT NOT NULL,
        PRIMARY KEY (source, target)
    )""")

    c.execute("""CREATE TABLE transitive_deps (
        source TEXT NOT NULL,
        target TEXT NOT NULL,
        distance INTEGER NOT NULL,
        PRIMARY KEY (source, target)
    )""")

    c.execute("""CREATE TABLE violations (
        package TEXT NOT NULL,
        violation_type TEXT NOT NULL,
        description TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE coupling_metrics (
        name TEXT PRIMARY KEY,
        afferent_coupling INTEGER NOT NULL,
        efferent_coupling INTEGER NOT NULL,
        instability REAL NOT NULL
    )""")

    # Insert packages
    for name, pkg in sorted(packages.items()):
        c.execute("INSERT INTO packages VALUES (?, ?, ?, ?)",
                  (name, pkg["layer"], pkg["layer_index"],
                   pkg["strict_dependencies"]))

    # Insert direct dependencies
    for name, pkg in sorted(packages.items()):
        for imp in pkg["imports"]:
            if imp in packages:
                c.execute("INSERT INTO dependencies VALUES (?, ?)", (name, imp))

    # Insert transitive deps with distances
    for source, dists in sorted(all_distances.items()):
        for target, distance in sorted(dists.items()):
            c.execute("INSERT INTO transitive_deps VALUES (?, ?, ?)",
                      (source, target, distance))

    # Insert violations
    for pkg_name, v_list in sorted(violations_data.items()):
        for v in v_list:
            c.execute("INSERT INTO violations VALUES (?, ?, ?)",
                      (pkg_name, v["type"], v["description"]))

    # Insert coupling metrics
    for name, m in sorted(coupling_metrics.items()):
        c.execute("INSERT INTO coupling_metrics VALUES (?, ?, ?, ?)",
                  (name, m["afferent_coupling"], m["efferent_coupling"],
                   m["instability"]))

    conn.commit()
    conn.close()


# ── Graphviz Visualization ──────────────────────────────────────


RATCHET_COLORS = {
    "false": "#FFFFFF",
    "layered": "#ADD8E6",
    "layered_dag": "#FFFACD",
    "dag": "#90EE90",
}


def generate_dot(packages, adj, violations_by_pkg, layers):
    """Generate DOT source for the dependency graph."""
    idx_to_name = {v: k for k, v in layers.items()}

    by_layer = defaultdict(list)
    for name, pkg in packages.items():
        by_layer[pkg["layer_index"]].append(name)

    violation_edges = set()
    for pkg_name, v_list in violations_by_pkg.items():
        for v in v_list:
            if v["type"] == "layering":
                violation_edges.add((pkg_name, v.get("imported_package", "")))

    lines = []
    lines.append("digraph dependencies {")
    lines.append("  rankdir=TB;")
    lines.append("  node [style=filled, shape=box, fontname=\"Helvetica\"];")
    lines.append("  edge [fontname=\"Helvetica\"];")
    lines.append("")

    for layer_idx in sorted(by_layer.keys()):
        layer_name = idx_to_name.get(layer_idx, f"layer_{layer_idx}")
        pkg_names = sorted(by_layer[layer_idx])
        lines.append(f"  subgraph cluster_{layer_name} {{")
        lines.append(f"    label=\"{layer_name}\";")
        lines.append(f"    style=dashed;")
        lines.append(f"    color=gray60;")
        lines.append(f"    fontname=\"Helvetica\";")
        for pname in pkg_names:
            color = RATCHET_COLORS.get(
                packages[pname]["strict_dependencies"], "#FFFFFF")
            lines.append(
                f"    {pname} [label=\"{pname}\", fillcolor=\"{color}\"];")
        lines.append("  }")
        lines.append("")

    for source in sorted(adj.keys()):
        for target in sorted(adj[source]):
            if target not in packages:
                continue
            if (source, target) in violation_edges:
                lines.append(
                    f"  {source} -> {target} [color=red, penwidth=2.0];")
            else:
                lines.append(f"  {source} -> {target};")

    lines.append("}")
    return "\n".join(lines)


def render_svg(dot_content, svg_path):
    dot_path = svg_path.replace(".svg", ".dot")
    with open(dot_path, "w") as f:
        f.write(dot_content)
    subprocess.run(
        ["dot", "-Tsvg", "-o", svg_path, dot_path],
        check=True, capture_output=True
    )


# ── Main Analysis ───────────────────────────────────────────────


def analyze(packages_dir, layers_path):
    layers = load_layers(layers_path)

    # Parse packages
    packages = {}
    for entry in sorted(os.listdir(packages_dir)):
        d = os.path.join(packages_dir, entry)
        if os.path.isdir(d) and os.path.isfile(os.path.join(d, "package.rb")):
            p = parse_package(d)
            p["layer_index"] = layers.get(p["layer"], -1)
            packages[p["name"]] = p

    # Build adjacency list
    adj = {name: list(p["imports"]) for name, p in packages.items()}
    all_nodes = set(packages.keys())

    # Compute transitive closure with BFS distances
    all_distances = {}
    for name in packages:
        all_distances[name] = bfs_distances(adj, name, all_nodes)

    # Find SCCs in the full graph
    full_sccs = find_sccs(adj, all_nodes)

    # Compute minimum feedback arc sets for each SCC
    fas_results = []
    for scc in sorted(full_sccs, key=lambda s: sorted(s)[0]):
        members = sorted(scc)
        fas_edges = compute_min_fas(adj, scc)
        fas_results.append({
            "members": members,
            "edges_to_remove": fas_edges,
        })

    # Compute coupling metrics
    coupling = compute_coupling(packages, adj)

    # Analyze each package
    results = {}
    violations_by_pkg = {}
    for name, pkg in packages.items():
        level = pkg["strict_dependencies"]
        level_idx = LEVEL_ORDER.index(level)
        violations = check_violations(pkg, packages, adj, layers)
        violations_by_pkg[name] = violations

        # Upgrade eligibility
        if level == "dag":
            can_upgrade = False
        elif violations:
            can_upgrade = False
        else:
            next_idx = level_idx + 1
            can_upgrade = not check_would_violate(pkg, packages, adj, next_idx)

        cm = coupling[name]
        results[name] = {
            "name": name,
            "layer": pkg["layer"],
            "layer_index": pkg["layer_index"],
            "strict_dependencies": level,
            "imports": pkg["imports"],
            "violations": violations,
            "can_upgrade": can_upgrade,
            "transitive_dep_count": len(all_distances[name]),
            "afferent_coupling": cm["afferent_coupling"],
            "efferent_coupling": cm["efferent_coupling"],
            "instability": cm["instability"],
        }

    # Summary
    by_level = defaultdict(int)
    violations_count = 0
    upgradeable_count = 0
    for r in results.values():
        by_level[r["strict_dependencies"]] += 1
        if r["violations"]:
            violations_count += 1
        if r["can_upgrade"]:
            upgradeable_count += 1

    report = {
        "packages": results,
        "summary": {
            "total_packages": len(packages),
            "violations_count": violations_count,
            "upgradeable_count": upgradeable_count,
            "by_level": dict(by_level),
            "scc_count": len(full_sccs),
            "largest_scc_size": max((len(s) for s in full_sccs), default=0),
        },
        "feedback_arc_sets": fas_results,
    }

    return report, packages, adj, all_distances, violations_by_pkg, layers, coupling


if __name__ == "__main__":
    report, packages, adj, all_distances, violations_by_pkg, layers, coupling = \
        analyze("/app/packages", "/app/layers.yml")

    # Write JSON report
    report_path = "/app/analysis_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    s = report["summary"]
    print(f"Report written to {report_path}")
    print(f"  Packages: {s['total_packages']}")
    print(f"  Violations: {s['violations_count']}")
    print(f"  Upgradeable: {s['upgradeable_count']}")
    print(f"  SCCs (size>1): {s['scc_count']}")
    print(f"  Largest SCC: {s['largest_scc_size']}")
    print(f"  FAS entries: {len(report['feedback_arc_sets'])}")

    # Create SQLite database
    db_path = "/app/deps.db"
    create_database(db_path, packages, adj, all_distances, violations_by_pkg,
                    coupling)
    print(f"Database written to {db_path}")

    # Generate Graphviz visualization
    svg_path = "/app/graph.svg"
    dot_content = generate_dot(packages, adj, violations_by_pkg, layers)
    render_svg(dot_content, svg_path)
    print(f"Graph rendered to {svg_path}")
