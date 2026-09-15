#!/usr/bin/env python3
"""
Solver for the parallel computation graph analysis task.
Parses program.cg, computes HB, MHP, races, work/span, minimum isolation.
Produces: analysis.db (SQLite), graph.dot + graph.svg (Graphviz), results.json.

"""

import json
import os
import re
import sqlite3
import subprocess
from collections import defaultdict
from itertools import combinations


def parse_cg(filepath):
    """Parse the .cg computation graph file."""
    nodes = {}
    accesses = defaultdict(list)
    typed_edges = []      # [(type, src, dst)]
    finish_scopes = {}

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            m = re.match(r'NODE\s+(\d+)\s+WEIGHT\s+(\d+)', line)
            if m:
                nodes[int(m.group(1))] = int(m.group(2))
                continue

            m = re.match(r'ACCESS\s+(\d+)\s+(READ|WRITE)\s+(\w+)', line)
            if m:
                accesses[int(m.group(1))].append((m.group(2), m.group(3)))
                continue

            m = re.match(r'(CONTINUE|SPAWN|FUTURE_GET)\s+(\d+)\s+->\s+(\d+)', line)
            if m:
                typed_edges.append((m.group(1), int(m.group(2)), int(m.group(3))))
                continue

            m = re.match(r'FINISH_SCOPE\s+(\w+)\s+PARENT\s+(\w+)', line)
            if m:
                scope_id = m.group(1)
                parent = None if m.group(2) == 'NONE' else m.group(2)
                finish_scopes[scope_id] = {"parent": parent, "members": [], "end": None}
                continue

            m = re.match(r'FINISH_MEMBER\s+(\w+)\s+(\d+)', line)
            if m:
                finish_scopes[m.group(1)]["members"].append(int(m.group(2)))
                continue

            m = re.match(r'FINISH_END\s+(\w+)\s+(\d+)', line)
            if m:
                finish_scopes[m.group(1)]["end"] = int(m.group(2))
                continue

    return nodes, accesses, typed_edges, finish_scopes


def build_direct_edges(typed_edges, finish_scopes):
    """Build complete set of direct HB edges including finish-scope joins."""
    flat_edges = set((src, dst) for _, src, dst in typed_edges)
    all_edges = set(flat_edges)

    for scope_id, scope in finish_scopes.items():
        end_node = scope["end"]
        if end_node is not None:
            for member in scope["members"]:
                if member != end_node:
                    all_edges.add((member, end_node))

    return all_edges


def transitive_closure(node_ids, direct_edges):
    """Compute transitive closure of happens-before."""
    reachable = defaultdict(set)
    adj = defaultdict(list)
    in_degree = defaultdict(int)

    for nid in node_ids:
        in_degree[nid] = 0
    for src, dst in direct_edges:
        adj[src].append(dst)
        in_degree[dst] += 1

    queue = [nid for nid in node_ids if in_degree[nid] == 0]
    topo_order = []
    while queue:
        queue.sort()
        node = queue.pop(0)
        topo_order.append(node)
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    for node in reversed(topo_order):
        new_reach = set()
        for succ in adj[node]:
            new_reach.add(succ)
            new_reach.update(reachable[succ])
        reachable[node] = new_reach

    return reachable


def compute_mhp(node_ids, reachable):
    """Compute May-Happen-in-Parallel pairs."""
    mhp_pairs = []
    for u, v in combinations(sorted(node_ids), 2):
        if v not in reachable[u] and u not in reachable[v]:
            mhp_pairs.append([u, v])
    return mhp_pairs


def detect_races(mhp_pairs, accesses):
    """Detect data races: MHP pairs with conflicting accesses."""
    races = []
    for pair in mhp_pairs:
        u, v = pair
        u_vars = {}
        for mode, var in accesses.get(u, []):
            u_vars.setdefault(var, set()).add(mode)
        v_vars = {}
        for mode, var in accesses.get(v, []):
            v_vars.setdefault(var, set()).add(mode)

        conflict_vars = []
        for var in sorted(set(u_vars) & set(v_vars)):
            if 'WRITE' in u_vars[var] or 'WRITE' in v_vars[var]:
                conflict_vars.append(var)

        if conflict_vars:
            races.append({"nodes": sorted(pair), "variables": sorted(conflict_vars)})

    return races


def compute_work_span(node_ids, nodes, direct_edges):
    """Compute total work and critical path length (span)."""
    work = sum(nodes[nid] for nid in node_ids)

    adj = defaultdict(list)
    in_degree = defaultdict(int)
    for nid in node_ids:
        in_degree[nid] = 0
    for src, dst in direct_edges:
        adj[src].append(dst)
        in_degree[dst] += 1

    queue = [nid for nid in node_ids if in_degree[nid] == 0]
    topo_order = []
    while queue:
        queue.sort()
        node = queue.pop(0)
        topo_order.append(node)
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    dist = {nid: nodes[nid] for nid in node_ids}
    for node in topo_order:
        for succ in adj[node]:
            if dist[node] + nodes[succ] > dist[succ]:
                dist[succ] = dist[node] + nodes[succ]

    span = max(dist.values())
    return work, span


def minimum_isolation(races):
    """Find minimum vertex cover on the race conflict graph via branch-and-bound."""
    if not races:
        return []

    race_edges = [(r["nodes"][0], r["nodes"][1]) for r in races]
    race_nodes = set()
    for n1, n2 in race_edges:
        race_nodes.add(n1)
        race_nodes.add(n2)

    best = [set(race_nodes)]

    def branch_bound(selected, remaining_edges, candidates, depth):
        if len(selected) >= len(best[0]):
            return
        if not remaining_edges:
            if len(selected) < len(best[0]):
                best[0] = set(selected)
            return

        edge = remaining_edges[0]
        n1, n2 = edge

        new_selected = selected | {n1}
        new_remaining = [e for e in remaining_edges if n1 not in e]
        branch_bound(new_selected, new_remaining, candidates - {n1}, depth + 1)

        new_selected = selected | {n2}
        new_remaining = [e for e in remaining_edges if n2 not in e]
        branch_bound(new_selected, new_remaining, candidates - {n2}, depth + 1)

    branch_bound(set(), race_edges, race_nodes, 0)
    return sorted(best[0])


def create_database(node_ids, nodes, hb_pairs, mhp_pairs, races,
                    work, span, ideal_parallelism, isolated_nodes):
    """Create SQLite database with analysis results."""
    db_path = "/app/analysis.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("CREATE TABLE nodes(id INTEGER PRIMARY KEY, weight INTEGER)")
    c.execute("CREATE TABLE happens_before(src INTEGER, dst INTEGER, PRIMARY KEY(src, dst))")
    c.execute("CREATE TABLE mhp_pairs(node1 INTEGER, node2 INTEGER, PRIMARY KEY(node1, node2))")
    c.execute("CREATE TABLE data_races(node1 INTEGER, node2 INTEGER, variable TEXT)")
    c.execute("CREATE TABLE metrics(key TEXT PRIMARY KEY, value REAL)")
    c.execute("CREATE TABLE isolated_nodes(node_id INTEGER PRIMARY KEY)")

    for nid in node_ids:
        c.execute("INSERT INTO nodes VALUES (?, ?)", (nid, nodes[nid]))

    for u, v in hb_pairs:
        c.execute("INSERT INTO happens_before VALUES (?, ?)", (u, v))

    for pair in mhp_pairs:
        c.execute("INSERT INTO mhp_pairs VALUES (?, ?)", (pair[0], pair[1]))

    for race in races:
        n1, n2 = race["nodes"]
        for var in race["variables"]:
            c.execute("INSERT INTO data_races VALUES (?, ?, ?)", (n1, n2, var))

    c.execute("INSERT INTO metrics VALUES ('work', ?)", (float(work),))
    c.execute("INSERT INTO metrics VALUES ('span', ?)", (float(span),))
    c.execute("INSERT INTO metrics VALUES ('ideal_parallelism', ?)", (ideal_parallelism,))

    for nid in isolated_nodes:
        c.execute("INSERT INTO isolated_nodes VALUES (?)", (nid,))

    conn.commit()
    conn.close()


def generate_dot(node_ids, nodes, typed_edges, finish_scopes, races, isolated_set):
    """Generate Graphviz DOT source for the computation graph."""
    lines = ['digraph CG {', '  rankdir=TB;', '  node [fontsize=10];']

    # Node declarations
    for nid in sorted(node_ids):
        shape = "doublecircle" if nid in isolated_set else "circle"
        weight = nodes[nid]
        lines.append(f'  N{nid} [label="N{nid}\\nw={weight}" shape={shape}];')

    # Direct edges with type-based colors
    direct_edge_set = set()
    color_map = {"CONTINUE": "black", "SPAWN": "blue", "FUTURE_GET": "green"}
    for etype, src, dst in typed_edges:
        color = color_map[etype]
        lines.append(f'  N{src} -> N{dst} [color={color}];')
        direct_edge_set.add((src, dst))

    # Finish-join edges (red), skipping those that duplicate direct edges
    for scope_id, scope in sorted(finish_scopes.items()):
        end_node = scope["end"]
        if end_node is not None:
            for member in sorted(scope["members"]):
                if member != end_node and (member, end_node) not in direct_edge_set:
                    lines.append(f'  N{member} -> N{end_node} [color=red];')

    # Race edges (dashed orange, undirected)
    for race in races:
        n1, n2 = race["nodes"]
        lines.append(f'  N{n1} -> N{n2} [color=orange style=dashed dir=none];')

    lines.append('}')
    return '\n'.join(lines)


def main():
    nodes, accesses, typed_edges, finish_scopes = parse_cg("/app/program.cg")
    node_ids = sorted(nodes.keys())

    # Build all direct edges (including finish-scope joins)
    direct_edges = build_direct_edges(typed_edges, finish_scopes)

    # Compute transitive closure
    reachable = transitive_closure(node_ids, direct_edges)

    # HB pairs
    hb_pairs = []
    for u in sorted(node_ids):
        for v in sorted(reachable[u]):
            hb_pairs.append([u, v])

    # MHP pairs
    mhp_pairs = compute_mhp(node_ids, reachable)

    # Data races
    data_races = detect_races(mhp_pairs, accesses)

    # Work and span
    work, span = compute_work_span(node_ids, nodes, direct_edges)
    ideal_parallelism = round(work / span, 4)

    # Minimum isolation set
    isolated_nodes = minimum_isolation(data_races)
    isolated_set = set(isolated_nodes)

    # --- Output artifact 1: SQLite database ---
    create_database(node_ids, nodes, hb_pairs, mhp_pairs, data_races,
                    work, span, ideal_parallelism, isolated_nodes)

    # --- Output artifact 2: Graphviz DOT + SVG ---
    dot_source = generate_dot(node_ids, nodes, typed_edges, finish_scopes,
                              data_races, isolated_set)
    with open("/app/graph.dot", "w") as f:
        f.write(dot_source)

    subprocess.run(
        ["dot", "-Tsvg", "-o", "/app/graph.svg", "/app/graph.dot"],
        check=True
    )

    # --- Output artifact 3: JSON report ---
    results = {
        "happens_before_pairs": hb_pairs,
        "mhp_pairs": mhp_pairs,
        "data_races": data_races,
        "work": work,
        "span": span,
        "ideal_parallelism": ideal_parallelism,
        "isolated_nodes": isolated_nodes,
    }
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Analysis complete.")
    print(f"  HB pairs: {len(hb_pairs)}")
    print(f"  MHP pairs: {len(mhp_pairs)}")
    print(f"  Data races: {len(data_races)}")
    print(f"  Work: {work}, Span: {span}, Ideal parallelism: {ideal_parallelism}")
    print(f"  Minimum isolation set ({len(isolated_nodes)} nodes): {isolated_nodes}")
    print(f"  Artifacts: analysis.db, graph.dot, graph.svg, results.json")


if __name__ == "__main__":
    main()
