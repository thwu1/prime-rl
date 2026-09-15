#!/usr/bin/env python3

"""
PFC Provenance Graph Forensics — reference solver.

1. Parse DOT topology for port-level adjacency.
2. Query SQLite for XOFF-validated PFC events.
3. Build directed provenance graph via temporal causal correlation.
4. Classify anomaly clusters (attack / deadlock).
5. Write results.json and provenance.dot.
"""

import json
import re
import sqlite3
from collections import defaultdict

# ── topology parsing ────────────────────────────────────────────────────────

def parse_dot_topology(path):
    """Parse Graphviz DOT file → adjacency dict  {(switch,port): (neighbor,port)}."""
    with open(path) as f:
        content = f.read()
    adj = {}
    pat = re.compile(
        r'(\w+)\s*--\s*(\w+)\s*\[.*?src_port="(\d+)".*?dst_port="(\d+)".*?\]'
    )
    for m in pat.finditer(content):
        s, d, sp, dp = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        adj[(s, sp)] = (d, dp)
        adj[(d, dp)] = (s, sp)
    return adj

# ── database helpers ────────────────────────────────────────────────────────

def load_pfc_config(conn):
    c = conn.cursor()
    c.execute("SELECT xoff_threshold_bytes, causal_window_us "
              "FROM pfc_config WHERE priority = 3")
    row = c.fetchone()
    return {"xoff_threshold": row[0], "causal_window_us": row[1]}


def extract_pfc_nodes(conn, xoff, min_count=10):
    """High-frequency PFC_PAUSE_SENT nodes with queue_depth >= XOFF."""
    c = conn.cursor()
    c.execute("""
        SELECT switch_id, port_id, queue_id, COUNT(*) AS cnt
        FROM pfc_events
        WHERE event_type = 'PFC_PAUSE_SENT'
          AND queue_depth_bytes >= ?
        GROUP BY switch_id, port_id, queue_id
        HAVING cnt >= ?
    """, (xoff, min_count))
    return {(r[0], r[1], r[2]): r[3] for r in c.fetchall()}


def get_timestamps(conn, sw, port, queue, xoff):
    c = conn.cursor()
    c.execute("""
        SELECT timestamp_us FROM pfc_events
        WHERE event_type = 'PFC_PAUSE_SENT'
          AND switch_id = ? AND port_id = ? AND queue_id = ?
          AND queue_depth_bytes >= ?
        ORDER BY timestamp_us
    """, (sw, port, queue, xoff))
    return [r[0] for r in c.fetchall()]


def get_pause_stats(conn, sw, port, queue, xoff):
    """Return (total_pause_us, min_ts, max_ts) for a node."""
    c = conn.cursor()
    c.execute("""
        SELECT SUM(pause_duration_us), MIN(timestamp_us), MAX(timestamp_us)
        FROM pfc_events
        WHERE event_type = 'PFC_PAUSE_SENT'
          AND switch_id = ? AND port_id = ? AND queue_id = ?
          AND queue_depth_bytes >= ?
    """, (sw, port, queue, xoff))
    return c.fetchone()

# ── provenance graph ────────────────────────────────────────────────────────

def causal_score(ts_a, ts_b, window):
    if not ts_a:
        return 0.0
    matches = j = 0
    for ta in ts_a:
        while j < len(ts_b) and ts_b[j] <= ta:
            j += 1
        if j < len(ts_b) and ts_b[j] - ta <= window:
            matches += 1
    return matches / len(ts_a)


def build_provenance(pfc_nodes, conn, adj, cfg):
    nodes = list(pfc_nodes.keys())
    xoff = cfg["xoff_threshold"]
    window = cfg["causal_window_us"]
    ts_cache = {n: get_timestamps(conn, *n, xoff) for n in nodes}
    edges = []
    for na in nodes:
        sw_a, pa, qa = na
        nb_info = adj.get((sw_a, pa))
        if nb_info is None:
            continue
        nb_sw, nb_port = nb_info
        for nb_ in nodes:
            sw_b, pb, qb = nb_
            if sw_b != nb_sw or pb == nb_port or qa != qb:
                continue
            if causal_score(ts_cache[na], ts_cache[nb_], window) > 0.5:
                edges.append((na, nb_))
    return edges

# ── graph analysis ──────────────────────────────────────────────────────────

def find_components(nodes, edges):
    graph = defaultdict(set)
    for a, b in edges:
        graph[a].add(b)
        graph[b].add(a)
    visited = set()
    components = []
    for node in nodes:
        if node in visited:
            continue
        comp = set()
        stack = [node]
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            comp.add(n)
            for nb in graph[n]:
                if nb not in visited:
                    stack.append(nb)
        if len(comp) > 1:
            components.append(comp)
    return components


def _directed_adj(component, edges):
    d = defaultdict(set)
    for a, b in edges:
        if a in component and b in component:
            d[a].add(b)
    return d


def has_cycle(component, edges):
    adj_d = _directed_adj(component, edges)
    W, G, B = 0, 1, 2
    color = {n: W for n in component}
    def dfs(n):
        color[n] = G
        for nb in adj_d[n]:
            if color[nb] == G:
                return True
            if color[nb] == W and dfs(nb):
                return True
        color[n] = B
        return False
    return any(dfs(n) for n in component if color[n] == W)


def extract_cycle(component, edges):
    adj_d = _directed_adj(component, edges)
    W, G, B = 0, 1, 2
    color = {n: W for n in component}
    def dfs(n, path):
        color[n] = G
        for nb in adj_d[n]:
            if color[nb] == G:
                return path[path.index(nb):]
            if color[nb] == W:
                r = dfs(nb, path + [nb])
                if r is not None:
                    return r
        color[n] = B
        return None
    for n in component:
        if color[n] == W:
            r = dfs(n, [n])
            if r is not None:
                return r
    return []


def find_root_and_depth(component, edges):
    in_deg = defaultdict(set)
    out_adj = defaultdict(set)
    for a, b in edges:
        if a in component and b in component:
            in_deg[b].add(a)
            out_adj[a].add(b)
    roots = [n for n in component if not in_deg[n]]
    root = roots[0] if roots else None
    depth = 0
    if root:
        frontier, visited = [root], {root}
        while frontier:
            nxt = []
            for n in frontier:
                for nb in out_adj[n]:
                    if nb not in visited:
                        visited.add(nb)
                        nxt.append(nb)
            if nxt:
                depth += 1
            frontier = nxt
    return root, depth


def compute_severity(component, conn, cfg):
    xoff = cfg["xoff_threshold"]
    total_pause = 0
    min_ts, max_ts = float("inf"), float("-inf")
    for sw, port, q in component:
        s, lo, hi = get_pause_stats(conn, sw, port, q, xoff)
        if s:
            total_pause += s
            min_ts = min(min_ts, lo)
            max_ts = max(max_ts, hi)
    span = max_ts - min_ts
    return round(total_pause / span, 2) if span > 0 else 0.0

# ── flow mapping ────────────────────────────────────────────────────────────

def map_flows(flows, components):
    comp_sw = [set(n[0] for n in c) for c in components]
    mapping = defaultdict(list)
    for f in flows:
        path_set = set(f["path"])
        for i, sw in enumerate(comp_sw):
            if path_set & sw:
                mapping[i].append(f["flow_id"])
    return mapping

# ── DOT output ──────────────────────────────────────────────────────────────

def provenance_dot(components, edges, anomalies):
    lines = ["digraph provenance {", "    rankdir=LR;",
             "    node [fontsize=10, style=filled];", ""]
    for i, (comp, anom) in enumerate(zip(components, anomalies)):
        atype = anom["type"]
        color = "red" if atype == "attack" else "orange"
        label = f"{atype.upper()} (id={anom['id']})"
        lines.append(f"    subgraph cluster_{i} {{")
        lines.append(f'        label="{label}";')
        lines.append(f'        color="{color}"; style=dashed;')
        for sw, p, q in comp:
            nid = f'"{sw}:{p}:{q}"'
            lines.append(f'        {nid} [label="{sw}:p{p}:q{q}", '
                         f'fillcolor="{color}"];')
        for a, b in edges:
            if a in comp and b in comp:
                lines.append(f'        "{a[0]}:{a[1]}:{a[2]}" -> '
                             f'"{b[0]}:{b[1]}:{b[2]}";')
        lines.append("    }")
        lines.append("")
    lines.append("}")
    return "\n".join(lines)

# ── main ────────────────────────────────────────────────────────────────────

def main():
    conn = sqlite3.connect("/app/fabric.db")
    cfg = load_pfc_config(conn)
    adj = parse_dot_topology("/app/topology.dot")

    with open("/app/victim_flows.json") as f:
        flows = json.load(f)

    pfc_nodes = extract_pfc_nodes(conn, cfg["xoff_threshold"])
    edges = build_provenance(pfc_nodes, conn, adj, cfg)
    components = find_components(list(pfc_nodes.keys()), edges)
    flow_map = map_flows(flows, components)

    anomalies = []
    for i, comp in enumerate(components):
        switches = sorted({n[0] for n in comp})
        af = sorted(flow_map.get(i, []))
        sev = compute_severity(comp, conn, cfg)

        if has_cycle(comp, edges):
            cy = extract_cycle(comp, edges)
            anomalies.append({
                "id": i, "type": "deadlock",
                "cycle_switches": [n[0] for n in cy],
                "cycle_length": len(cy),
                "affected_switches": switches,
                "affected_flow_ids": af,
                "severity_score": sev,
            })
        else:
            root, depth = find_root_and_depth(comp, edges)
            anomalies.append({
                "id": i, "type": "attack",
                "root_cause": {"switch": root[0], "port": root[1],
                               "queue": root[2]},
                "propagation_depth": depth,
                "affected_switches": switches,
                "affected_flow_ids": af,
                "severity_score": sev,
            })

    results = {"anomaly_count": len(anomalies), "anomalies": anomalies}
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    with open("/app/provenance.dot", "w") as f:
        f.write(provenance_dot(components, edges, anomalies))

    conn.close()
    print(f"Done: {len(anomalies)} anomalies")
    for a in anomalies:
        print(f"  [{a['id']}] {a['type']}: sw={a['affected_switches']} "
              f"flows={a['affected_flow_ids']} severity={a['severity_score']}")


if __name__ == "__main__":
    main()
