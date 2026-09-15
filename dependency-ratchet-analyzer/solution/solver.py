#!/usr/bin/env python3
"""
Solution: dependency ratchet audit and migration analyzer.
Reads from /app/monolith.db and /app/runtime_scan.csv,
produces /app/output/report.json and /app/output/graph.svg.

"""
import csv
import json
import os
import sqlite3
import subprocess
from collections import defaultdict

LAYER_ORDER = {"utility": 0, "power": 1, "business": 2, "api": 3, "services": 4}
LEVEL_ORDER = {"false": 0, "layered": 1, "layered_dag": 2, "dag": 3}
LEVEL_NAMES = ["false", "layered", "layered_dag", "dag"]


# ---- Data Loading ----


def load_packages(db_path="/app/monolith.db"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    pkgs = {}
    cur.execute("""
        SELECT p.name, l.name as layer, p.enforcement_level
        FROM packages p JOIN layers l ON p.layer_id = l.id
    """)
    for row in cur.fetchall():
        cur2 = conn.cursor()
        cur2.execute("SELECT target FROM dependencies WHERE source = ?", (row["name"],))
        deps = [r[0] for r in cur2.fetchall()]
        pkgs[row["name"]] = {
            "name": row["name"],
            "layer": row["layer"],
            "strict_dependencies": row["enforcement_level"],
            "dependencies": deps,
        }
    conn.close()
    return pkgs


def parse_runtime_scan(scan_path="/app/runtime_scan.csv"):
    """Parse runtime scan CSV and return unique (source, target, evidence) tuples."""
    seen = {}
    with open(scan_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            src = row["source_package"].strip()
            tgt = row["target_package"].strip()
            key = (src, tgt)
            if key not in seen:
                seen[key] = row["source_module"].strip()
    return [(s, t, ev) for (s, t), ev in seen.items()]


def find_undeclared_deps(pkgs, runtime_deps):
    """Find deps in runtime scan not present in the static graph."""
    undeclared = []
    for src, tgt, evidence in runtime_deps:
        if src in pkgs and tgt in pkgs:
            if tgt not in pkgs[src]["dependencies"]:
                undeclared.append((src, tgt, evidence))
    return sorted(undeclared, key=lambda x: (x[0], x[1]))


def merge_runtime_deps(pkgs, undeclared):
    """Add undeclared runtime deps to the in-memory graph."""
    for src, tgt, _ in undeclared:
        if tgt not in pkgs[src]["dependencies"]:
            pkgs[src]["dependencies"].append(tgt)


# ---- Violation Checking ----


def check_layered_violations(pkg, pkgs):
    violations = []
    my_rank = LAYER_ORDER[pkg["layer"]]
    for dep in sorted(pkg["dependencies"]):
        dep_rank = LAYER_ORDER[pkgs[dep]["layer"]]
        if dep_rank > my_rank:
            violations.append({
                "package": pkg["name"],
                "dependency": dep,
                "rule": "layered",
                "reason": (
                    f"Depends on '{dep}' in layer '{pkgs[dep]['layer']}' "
                    f"(rank {dep_rank}) which is above '{pkg['layer']}' (rank {my_rank})"
                ),
            })
    return violations


def _find_reachable_same_layer(pkg_name, pkgs):
    """Find all same-layer nodes reachable via same-layer edges."""
    my_layer = pkgs[pkg_name]["layer"]
    reachable = set()
    stack = [pkg_name]
    while stack:
        node = stack.pop()
        if node in reachable:
            continue
        reachable.add(node)
        for dep in pkgs[node]["dependencies"]:
            if pkgs[dep]["layer"] == my_layer and dep not in reachable:
                stack.append(dep)
    return reachable


def _find_cycle_nodes_in_subgraph(nodes, pkgs, layer):
    """Find all nodes in SCCs of size >= 2 within a same-layer subgraph."""
    adj = defaultdict(list)
    for node in nodes:
        for dep in pkgs[node]["dependencies"]:
            if dep in nodes and pkgs[dep]["layer"] == layer:
                adj[node].append(dep)

    index_counter = [0]
    stack = []
    lowlink = {}
    index = {}
    on_stack = {}
    cycle_nodes = set()

    def strongconnect(v):
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True

        for w in adj[v]:
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
            if len(scc) >= 2:
                cycle_nodes.update(scc)

    for v in sorted(nodes):
        if v not in index:
            strongconnect(v)

    return cycle_nodes


def check_layered_dag_violations(pkg, pkgs):
    violations = check_layered_violations(pkg, pkgs)
    my_layer = pkg["layer"]

    reachable = _find_reachable_same_layer(pkg["name"], pkgs)
    if len(reachable) <= 1:
        return violations

    cycle_nodes = _find_cycle_nodes_in_subgraph(reachable, pkgs, my_layer)
    if cycle_nodes:
        for dep in sorted(pkg["dependencies"]):
            if pkgs[dep]["layer"] == my_layer and dep in cycle_nodes:
                violations.append({
                    "package": pkg["name"],
                    "dependency": dep,
                    "rule": "layered_dag",
                    "reason": (
                        f"Same-layer dependency '{dep}' participates in a cycle "
                        f"within the reachable subgraph of layer '{my_layer}'"
                    ),
                })
    return violations


def _find_cycle_nodes_in_reachable(start_pkg, pkgs):
    """Find all cycle-participating nodes in the full reachable subgraph from start_pkg."""
    reachable = set()
    stack = [start_pkg]
    while stack:
        node = stack.pop()
        if node in reachable:
            continue
        reachable.add(node)
        for dep in pkgs[node]["dependencies"]:
            stack.append(dep)

    adj = defaultdict(list)
    for node in reachable:
        for dep in pkgs[node]["dependencies"]:
            if dep in reachable:
                adj[node].append(dep)

    index_counter = [0]
    scc_stack = []
    lowlink = {}
    index = {}
    on_stack = {}
    cycle_nodes = set()

    def strongconnect(v):
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        scc_stack.append(v)
        on_stack[v] = True

        for w in adj[v]:
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif on_stack.get(w, False):
                lowlink[v] = min(lowlink[v], index[w])

        if lowlink[v] == index[v]:
            scc = []
            while True:
                w = scc_stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == v:
                    break
            if len(scc) >= 2:
                cycle_nodes.update(scc)

    for v in sorted(reachable):
        if v not in index:
            strongconnect(v)

    return cycle_nodes


def check_dag_violations(pkg, pkgs):
    violations = check_layered_violations(pkg, pkgs)
    cycle_nodes = _find_cycle_nodes_in_reachable(pkg["name"], pkgs)
    if cycle_nodes:
        for dep in sorted(pkg["dependencies"]):
            if dep in cycle_nodes:
                violations.append({
                    "package": pkg["name"],
                    "dependency": dep,
                    "rule": "dag",
                    "reason": (
                        f"Dependency '{dep}' participates in a cycle "
                        f"in the transitive dependency closure"
                    ),
                })
    return violations


def check_violations_at_level(pkg_name, level, pkgs):
    fake_pkg = dict(pkgs[pkg_name])
    fake_pkg["strict_dependencies"] = level
    if level == "layered":
        return check_layered_violations(fake_pkg, pkgs)
    elif level == "layered_dag":
        return check_layered_dag_violations(fake_pkg, pkgs)
    elif level == "dag":
        return check_dag_violations(fake_pkg, pkgs)
    return []


def compute_violations(pkgs):
    all_violations = []
    for name in sorted(pkgs):
        pkg = pkgs[name]
        level = pkg["strict_dependencies"]
        if level == "false":
            continue
        elif level == "layered":
            all_violations.extend(check_layered_violations(pkg, pkgs))
        elif level == "layered_dag":
            all_violations.extend(check_layered_dag_violations(pkg, pkgs))
        elif level == "dag":
            all_violations.extend(check_dag_violations(pkg, pkgs))
    return sorted(all_violations, key=lambda v: (v["package"], v["dependency"]))


# ---- Audit: Invalid Levels ----


def compute_invalid_levels(pkgs):
    invalid = []
    for name in sorted(pkgs):
        pkg = pkgs[name]
        level = pkg["strict_dependencies"]
        if level == "false":
            continue
        viols = check_violations_at_level(name, level, pkgs)
        if viols:
            max_valid = "false"
            current_rank = LEVEL_ORDER[level]
            for r in range(current_rank - 1, 0, -1):
                test_level = LEVEL_NAMES[r]
                if not check_violations_at_level(name, test_level, pkgs):
                    max_valid = test_level
                    break
            invalid.append({
                "package": name,
                "current_level": level,
                "max_valid_level": max_valid,
            })
    return invalid


def apply_corrections(pkgs, invalid_levels):
    """Apply level corrections to package data."""
    for entry in invalid_levels:
        pkgs[entry["package"]]["strict_dependencies"] = entry["max_valid_level"]


# ---- SCC Detection ----


def tarjan_scc(pkgs):
    index_counter = [0]
    stack = []
    lowlink = {}
    index = {}
    on_stack = {}
    result = []

    def strongconnect(v):
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True

        for w in pkgs[v]["dependencies"]:
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
            if len(scc) >= 2:
                result.append(sorted(scc))

    for v in sorted(pkgs):
        if v not in index:
            strongconnect(v)

    return sorted(result)


# ---- Feedback Arc Set ----


def compute_critical_edges(pkgs):
    sccs = tarjan_scc(pkgs)
    critical = []

    for scc in sccs:
        scc_set = set(scc)
        edges = set()
        for node in scc:
            for dep in pkgs[node]["dependencies"]:
                if dep in scc_set:
                    edges.add((node, dep))

        while True:
            sub_sccs = _find_sccs_in_edge_subgraph(scc_set, edges)
            if not sub_sccs:
                break

            for sub_scc in sub_sccs:
                sub_set = set(sub_scc)
                in_deg = defaultdict(int)
                out_deg = defaultdict(int)
                sub_edges = []
                for s, t in edges:
                    if s in sub_set and t in sub_set:
                        out_deg[s] += 1
                        in_deg[t] += 1
                        sub_edges.append((s, t))

                best_edge = None
                best_ratio = -1
                for s, t in sorted(sub_edges):
                    od = out_deg[s] if out_deg[s] > 0 else 1
                    ratio = in_deg[s] / od
                    if ratio > best_ratio or (
                        ratio == best_ratio
                        and (best_edge is None or (s, t) < best_edge)
                    ):
                        best_ratio = ratio
                        best_edge = (s, t)

                if best_edge:
                    critical.append({"source": best_edge[0], "target": best_edge[1]})
                    edges.discard(best_edge)

    return sorted(critical, key=lambda e: (e["source"], e["target"]))


def _find_sccs_in_edge_subgraph(nodes, edges):
    adj = defaultdict(list)
    for s, t in edges:
        if s in nodes and t in nodes:
            adj[s].append(t)

    index_counter = [0]
    stack = []
    lowlink = {}
    index = {}
    on_stack = {}
    result = []

    def strongconnect(v):
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True

        for w in adj[v]:
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
            if len(scc) >= 2:
                result.append(sorted(scc))

    for v in sorted(nodes):
        if v not in index:
            strongconnect(v)

    return result


# ---- Promotability ----


def compute_promotable(pkgs):
    promotable = []
    for name in sorted(pkgs):
        pkg = pkgs[name]
        current_rank = LEVEL_ORDER[pkg["strict_dependencies"]]
        if current_rank >= 3:
            continue
        best_level = None
        for target_rank in range(current_rank + 1, 4):
            target_level = LEVEL_NAMES[target_rank]
            viols = check_violations_at_level(name, target_level, pkgs)
            if not viols:
                best_level = target_level
            else:
                break
        if best_level:
            promotable.append({
                "package": name,
                "current": pkg["strict_dependencies"],
                "promoted_to": best_level,
            })
    return promotable


# ---- Migration Plan ----


def compute_migration_plan(pkgs):
    current_levels = {name: pkg["strict_dependencies"] for name, pkg in pkgs.items()}
    steps = []
    step_num = 1

    changed = True
    while changed:
        changed = False
        candidates = sorted(
            pkgs.keys(), key=lambda n: (LAYER_ORDER[pkgs[n]["layer"]], n)
        )

        for name in candidates:
            current_rank = LEVEL_ORDER[current_levels[name]]
            if current_rank >= 3:
                continue
            next_rank = current_rank + 1
            next_level = LEVEL_NAMES[next_rank]

            viols = check_violations_at_level(name, next_level, pkgs)
            if not viols:
                steps.append({
                    "step": step_num,
                    "package": name,
                    "from": LEVEL_NAMES[current_rank],
                    "to": next_level,
                })
                current_levels[name] = next_level
                step_num += 1
                changed = True
                break

    return steps


# ---- Graph Visualization ----


def generate_graph_svg(pkgs, cycles, output_dir="/app/output"):
    cycle_members = set()
    for scc in cycles:
        cycle_members.update(scc)

    cycle_edges = set()
    for scc in cycles:
        scc_set = set(scc)
        for node in scc:
            for dep in pkgs[node]["dependencies"]:
                if dep in scc_set:
                    cycle_edges.add((node, dep))

    lines = [
        "digraph monolith {",
        "  rankdir=TB;",
        '  node [shape=box, style=filled, fillcolor=lightyellow];',
    ]

    layer_groups = defaultdict(list)
    for name, pkg in pkgs.items():
        layer_groups[pkg["layer"]].append(name)

    for layer in ["utility", "power", "business", "api", "services"]:
        lines.append(f"  subgraph cluster_{layer} {{")
        lines.append(f'    label="{layer}";')
        for name in sorted(layer_groups[layer]):
            color = "salmon" if name in cycle_members else "lightyellow"
            lines.append(f'    "{name}" [fillcolor={color}];')
        lines.append("  }")

    for name in sorted(pkgs.keys()):
        for dep in sorted(pkgs[name]["dependencies"]):
            if (name, dep) in cycle_edges:
                lines.append(
                    f'  "{name}" -> "{dep}" [color=red, penwidth=2.0];'
                )
            else:
                lines.append(f'  "{name}" -> "{dep}";')

    lines.append("}")

    dot_path = os.path.join(output_dir, "graph.dot")
    svg_path = os.path.join(output_dir, "graph.svg")

    with open(dot_path, "w") as f:
        f.write("\n".join(lines))

    subprocess.run(["dot", "-Tsvg", "-o", svg_path, dot_path], check=True)


# ---- Main ----


def main():
    pkgs = load_packages()

    # Step 1: Parse runtime scan and find undeclared deps
    runtime_deps = parse_runtime_scan()
    undeclared = find_undeclared_deps(pkgs, runtime_deps)
    merge_runtime_deps(pkgs, undeclared)

    # Step 2: Audit - compute violations at current levels on complete graph
    violations = compute_violations(pkgs)
    invalid_levels = compute_invalid_levels(pkgs)

    # Step 3: Compute cycles and critical edges on complete graph
    cycles = tarjan_scc(pkgs)
    critical_edges = compute_critical_edges(pkgs)

    # Step 4: Apply corrections and compute forward plan
    apply_corrections(pkgs, invalid_levels)
    promotable = compute_promotable(pkgs)
    migration_plan = compute_migration_plan(pkgs)

    # Build report
    report = {
        "audit": {
            "undeclared_dependencies": [
                {"source": u[0], "target": u[1], "evidence": u[2]}
                for u in undeclared
            ],
            "invalid_levels": invalid_levels,
        },
        "violations": violations,
        "cycles": cycles,
        "critical_edges": critical_edges,
        "promotable": promotable,
        "migration_plan": migration_plan,
    }

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/report.json", "w") as f:
        json.dump(report, f, indent=2)

    generate_graph_svg(pkgs, cycles)

    print(f"Report: /app/output/report.json")
    print(f"Graph:  /app/output/graph.svg")
    print(f"  Undeclared deps:  {len(undeclared)}")
    print(f"  Invalid levels:   {len(invalid_levels)}")
    print(f"  Violations:       {len(violations)}")
    print(f"  Cycles (SCCs):    {len(cycles)}")
    print(f"  Critical edges:   {len(critical_edges)}")
    print(f"  Promotable:       {len(promotable)}")
    print(f"  Migration steps:  {len(migration_plan)}")


if __name__ == "__main__":
    main()
