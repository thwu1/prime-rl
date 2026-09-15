#!/usr/bin/env python3

"""
OSPF LFA Coverage and Link-Failure Sensitivity Analyzer.
Parses FRRouting configuration dumps, computes SPF and RFC 5286 LFA coverage,
performs link-failure sensitivity analysis, creates SQLite routing database,
and generates Graphviz topology diagrams.
"""

import json
import heapq
import os
import sqlite3
import subprocess
from collections import defaultdict


# ── FRR Config Parser ────────────────────────────────────────────


def parse_frr_configs(config_path):
    """Parse consolidated FRR config dump to extract network topology."""
    with open(config_path) as f:
        content = f.read()

    routers = {}
    interfaces = {}
    current_router = None
    current_iface = None
    in_router_ospf = False

    for line in content.split("\n"):
        stripped = line.strip()

        if stripped.startswith("hostname "):
            current_router = stripped.split()[1]
            if current_router not in routers:
                routers[current_router] = {"router_id": None, "loopback": None}
                interfaces[current_router] = {}
            current_iface = None
            in_router_ospf = False
            continue

        if stripped == "end":
            current_router = None
            current_iface = None
            in_router_ospf = False
            continue

        if not current_router:
            continue

        if stripped.startswith("interface ") and not in_router_ospf:
            current_iface = stripped.split()[1]
            if current_iface not in interfaces[current_router]:
                interfaces[current_router][current_iface] = {
                    "ip": None, "prefix_len": None, "cost": 1
                }
            continue

        if stripped.startswith("ip address ") and current_iface:
            parts = stripped.split()
            ip_cidr = parts[2]
            ip, prefix_len = ip_cidr.split("/")
            interfaces[current_router][current_iface]["ip"] = ip
            interfaces[current_router][current_iface]["prefix_len"] = int(prefix_len)
            if current_iface == "lo" or current_iface.startswith("lo"):
                if interfaces[current_router][current_iface]["prefix_len"] == 32:
                    routers[current_router]["loopback"] = ip
            continue

        if stripped.startswith("ip ospf cost ") and current_iface:
            cost = int(stripped.split()[-1])
            interfaces[current_router][current_iface]["cost"] = cost
            continue

        if stripped == "router ospf":
            in_router_ospf = True
            current_iface = None
            continue

        if stripped.startswith("ospf router-id ") and in_router_ospf:
            rid = stripped.split()[-1]
            routers[current_router]["router_id"] = rid
            continue

        if stripped == "!":
            current_iface = None
            in_router_ospf = False
            continue

    # Correlate /30 subnets across routers to discover links
    subnet_ifaces = defaultdict(list)
    for router, ifaces in interfaces.items():
        for iface_name, iface_data in ifaces.items():
            if iface_data["ip"] is None or iface_data["prefix_len"] != 30:
                continue
            ip_parts = list(map(int, iface_data["ip"].split(".")))
            ip_int = (ip_parts[0] << 24) | (ip_parts[1] << 16) | (ip_parts[2] << 8) | ip_parts[3]
            mask = (0xFFFFFFFF << (32 - 30)) & 0xFFFFFFFF
            net_int = ip_int & mask
            net_addr = (
                f"{(net_int >> 24) & 0xFF}.{(net_int >> 16) & 0xFF}."
                f"{(net_int >> 8) & 0xFF}.{net_int & 0xFF}"
            )
            subnet = f"{net_addr}/30"
            subnet_ifaces[subnet].append({
                "router": router,
                "iface": iface_name,
                "ip": iface_data["ip"],
                "cost": iface_data["cost"],
            })

    links = []
    seen = set()
    for subnet, ifaces in subnet_ifaces.items():
        if len(ifaces) == 2:
            a, b = sorted([ifaces[0]["router"], ifaces[1]["router"]])
            key = (a, b)
            if key not in seen:
                seen.add(key)
                cost_a = ifaces[0]["cost"] if ifaces[0]["router"] == a else ifaces[1]["cost"]
                links.append({
                    "from": a,
                    "to": b,
                    "cost": cost_a,
                    "subnet": subnet,
                })

    return {
        "routers": routers,
        "router_names": sorted(routers.keys()),
        "links": links,
        "source": "R1",
    }


# ── Graph Algorithms ─────────────────────────────────────────────


def build_adjacency(router_names, links, exclude_link=None):
    """Build adjacency dict, optionally excluding a link."""
    adj = defaultdict(dict)
    for link in links:
        if exclude_link:
            key = tuple(sorted([link["from"], link["to"]]))
            if key == exclude_link:
                continue
        adj[link["from"]][link["to"]] = link["cost"]
        adj[link["to"]][link["from"]] = link["cost"]
    for r in router_names:
        if r not in adj:
            adj[r] = {}
    return dict(adj)


def dijkstra(adj, source):
    """Dijkstra with ECMP predecessor tracking."""
    dist = {r: float("inf") for r in adj}
    dist[source] = 0
    preds = {r: [] for r in adj}
    visited = set()
    heap = [(0, source)]

    while heap:
        d, u = heapq.heappop(heap)
        if u in visited:
            continue
        visited.add(u)
        for v, w in adj[u].items():
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                preds[v] = [u]
                heapq.heappush(heap, (nd, v))
            elif nd == dist[v] and u not in preds[v]:
                preds[v].append(u)

    return dist, preds


def trace_next_hops(preds, source, dest):
    """Trace predecessor chain to find all first-hop routers from source."""
    if dest == source:
        return []
    nhs = set()
    stack = [dest]
    visited = set()
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        for p in preds[node]:
            if p == source:
                nhs.add(node)
            else:
                stack.append(p)
    return sorted(nhs)


def compute_all_pairs_dist(adj):
    """Compute shortest-path distances from every router."""
    all_dist = {}
    for r in adj:
        d, _ = dijkstra(adj, r)
        all_dist[r] = d
    return all_dist


def compute_spf(adj, source):
    """Compute SPF results from source."""
    dist, preds = dijkstra(adj, source)
    result = {}
    for r in sorted(adj.keys()):
        if r == source:
            continue
        if dist[r] == float("inf"):
            continue
        result[r] = {
            "distance": dist[r],
            "next_hops": trace_next_hops(preds, source, r),
        }
    return result


def compute_lfa(adj, source, all_dist):
    """Compute LFA per RFC 5286 for each (dest, next-hop) pair."""
    source_dist = all_dist[source]
    _, preds = dijkstra(adj, source)
    neighbors = sorted(adj[source].keys())

    results = {}
    for dest in sorted(adj.keys()):
        if dest == source:
            continue
        if source_dist[dest] == float("inf"):
            continue

        nhs = trace_next_hops(preds, source, dest)
        if not nhs:
            continue
        results[dest] = {}

        for nh in nhs:
            best_lfa = None
            best_type = "none"
            best_dist_to_dest = float("inf")

            for n in neighbors:
                if n == nh:
                    continue

                d_n_dest = all_dist[n][dest]
                if d_n_dest == float("inf"):
                    continue
                d_n_source = all_dist[n][source]
                d_source_dest = source_dist[dest]

                # Loop-free criterion (RFC 5286 Inequality 1)
                if d_n_dest >= d_n_source + d_source_dest:
                    continue

                # Determine protection type
                if dest == nh:
                    ptype = "link"
                else:
                    d_n_nh = all_dist[n][nh]
                    d_nh_dest = all_dist[nh][dest]
                    if d_n_nh == float("inf") or d_nh_dest == float("inf"):
                        ptype = "node"
                    elif d_n_dest < d_n_nh + d_nh_dest:
                        ptype = "node"
                    else:
                        ptype = "link"

                # Selection: node > link > none; shortest dist; alphabetical
                if ptype == "node" and best_type != "node":
                    best_lfa = n
                    best_type = ptype
                    best_dist_to_dest = d_n_dest
                elif ptype == best_type:
                    if d_n_dest < best_dist_to_dest or (
                        d_n_dest == best_dist_to_dest
                        and (best_lfa is None or n < best_lfa)
                    ):
                        best_lfa = n
                        best_type = ptype
                        best_dist_to_dest = d_n_dest
                elif ptype == "link" and best_type == "none":
                    best_lfa = n
                    best_type = ptype
                    best_dist_to_dest = d_n_dest

            results[dest][nh] = {"lfa": best_lfa, "type": best_type}

    return results


def compute_coverage(lfa_results):
    """Classify each destination's protection level."""
    total = len(lfa_results)
    fully = partial = unprotected = 0
    unprotected_list = []
    partial_list = []

    for dest in sorted(lfa_results.keys()):
        nh_map = lfa_results[dest]
        has_none = any(v["type"] == "none" for v in nh_map.values())
        has_link_only = any(
            v["type"] == "link" and dest != nh for nh, v in nh_map.items()
        )

        if has_none:
            unprotected += 1
            unprotected_list.append(dest)
        elif has_link_only:
            partial += 1
            partial_list.append(dest)
        else:
            fully += 1

    return {
        "total_destinations": total,
        "fully_protected": fully,
        "partially_protected": partial,
        "unprotected": unprotected,
        "unprotected_list": sorted(unprotected_list),
        "partially_protected_list": sorted(partial_list),
    }


# ── SQLite Database ──────────────────────────────────────────────


def create_sqlite_db(db_path, topo, spf_results, lfa_results):
    """Create and populate SQLite routing information database."""
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE routers (
            name TEXT PRIMARY KEY,
            router_id TEXT NOT NULL,
            loopback TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE links (
            router_a TEXT NOT NULL,
            router_b TEXT NOT NULL,
            cost INTEGER NOT NULL,
            subnet TEXT NOT NULL,
            PRIMARY KEY (router_a, router_b)
        )
    """)

    c.execute("""
        CREATE TABLE spf_results (
            destination TEXT NOT NULL,
            distance INTEGER NOT NULL,
            next_hop TEXT NOT NULL,
            PRIMARY KEY (destination, next_hop)
        )
    """)

    c.execute("""
        CREATE TABLE lfa_results (
            destination TEXT NOT NULL,
            next_hop TEXT NOT NULL,
            lfa_neighbor TEXT,
            protection_type TEXT NOT NULL,
            PRIMARY KEY (destination, next_hop)
        )
    """)

    # Populate routers
    for name, info in sorted(topo["routers"].items()):
        c.execute(
            "INSERT INTO routers (name, router_id, loopback) VALUES (?, ?, ?)",
            (name, info["router_id"], info["loopback"]),
        )

    # Populate links
    for link in topo["links"]:
        c.execute(
            "INSERT INTO links (router_a, router_b, cost, subnet) VALUES (?, ?, ?, ?)",
            (link["from"], link["to"], link["cost"], link["subnet"]),
        )

    # Populate SPF results
    for dest, data in spf_results.items():
        for nh in data["next_hops"]:
            c.execute(
                "INSERT INTO spf_results (destination, distance, next_hop) VALUES (?, ?, ?)",
                (dest, data["distance"], nh),
            )

    # Populate LFA results
    for dest, nhs in lfa_results.items():
        for nh, info in nhs.items():
            c.execute(
                "INSERT INTO lfa_results (destination, next_hop, lfa_neighbor, protection_type) "
                "VALUES (?, ?, ?, ?)",
                (dest, nh, info["lfa"], info["type"]),
            )

    conn.commit()
    conn.close()


# ── Sensitivity Analysis ────────────────────────────────────────


def compute_sensitivity(router_names, links, source):
    """For each link, simulate removal and recompute LFA coverage."""
    all_dests = set(r for r in router_names if r != source)
    results = {}

    for link in links:
        key = "-".join(sorted([link["from"], link["to"]]))
        exclude = tuple(sorted([link["from"], link["to"]]))

        mod_adj = build_adjacency(router_names, links, exclude_link=exclude)
        mod_all_dist = compute_all_pairs_dist(mod_adj)

        spf = compute_spf(mod_adj, source)
        reachable = set(spf.keys())
        unreachable = sorted(all_dests - reachable)

        lfa = compute_lfa(mod_adj, source, mod_all_dist)
        coverage = compute_coverage(lfa)

        results[key] = {
            "unreachable": unreachable,
            "coverage": {
                "total_destinations": coverage["total_destinations"],
                "fully_protected": coverage["fully_protected"],
                "partially_protected": coverage["partially_protected"],
                "unprotected": coverage["unprotected"],
            },
        }

    return results


# ── Graphviz Topology Diagram ────────────────────────────────────


def generate_topology_svg(output_path, router_names, links, source):
    """Generate DOT graph and render to SVG via graphviz."""
    dot_lines = [
        "graph OSPF_Network {",
        '    graph [layout=neato, overlap=false, splines=true];',
        '    node [shape=ellipse, style=filled, fillcolor=lightblue, fontname="Helvetica"];',
        '    edge [fontname="Helvetica", fontsize=10];',
        "",
    ]

    for r in sorted(router_names):
        if r == source:
            dot_lines.append(f'    {r} [fillcolor=gold, penwidth=2.0];')
        else:
            dot_lines.append(f"    {r};")

    dot_lines.append("")

    for link in links:
        a, b = link["from"], link["to"]
        cost = link["cost"]
        dot_lines.append(f'    {a} -- {b} [label="{cost}"];')

    dot_lines.append("}")

    dot_content = "\n".join(dot_lines)
    dot_path = "/tmp/topology.dot"

    with open(dot_path, "w") as f:
        f.write(dot_content)

    subprocess.run(
        ["dot", "-Tsvg", "-o", output_path, dot_path],
        check=True,
        capture_output=True,
    )


# ── Main ─────────────────────────────────────────────────────────


def main():
    # Parse FRR configs
    topo = parse_frr_configs("/app/network_dump.conf")
    router_names = topo["router_names"]
    links = topo["links"]
    source = topo["source"]

    # Build adjacency
    adj = build_adjacency(router_names, links)

    # Compute all-pairs shortest paths
    all_dist = compute_all_pairs_dist(adj)

    # SPF from source
    spf_results = compute_spf(adj, source)

    # LFA computation
    lfa_results = compute_lfa(adj, source, all_dist)

    # Coverage summary
    coverage = compute_coverage(lfa_results)

    # Create output directory
    os.makedirs("/app/results", exist_ok=True)

    # Write JSON outputs
    with open("/app/results/spf.json", "w") as f:
        json.dump(spf_results, f, indent=2, sort_keys=True)

    with open("/app/results/lfa.json", "w") as f:
        json.dump(lfa_results, f, indent=2, sort_keys=True)

    with open("/app/results/coverage.json", "w") as f:
        json.dump(coverage, f, indent=2, sort_keys=True)

    # Create SQLite database
    create_sqlite_db("/app/results/ospf_rib.db", topo, spf_results, lfa_results)

    # Sensitivity analysis
    sensitivity = compute_sensitivity(router_names, links, source)
    with open("/app/results/sensitivity.json", "w") as f:
        json.dump(sensitivity, f, indent=2, sort_keys=True)

    # Generate topology SVG
    generate_topology_svg("/app/results/topology.svg", router_names, links, source)

    # Summary output
    print("OSPF LFA analysis complete. Results written to /app/results/")
    print(f"  SPF: {len(spf_results)} destinations")
    print(
        f"  Coverage: {coverage['fully_protected']} full, "
        f"{coverage['partially_protected']} partial, "
        f"{coverage['unprotected']} unprotected"
    )
    print(f"  Sensitivity: {len(sensitivity)} link-failure scenarios analyzed")
    print(f"  SQLite DB: /app/results/ospf_rib.db")
    print(f"  Topology: /app/results/topology.svg")


if __name__ == "__main__":
    main()
