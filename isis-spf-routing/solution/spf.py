#!/usr/bin/env python3

"""
IS-IS SPF Routing Table Calculator

Reads LSDB from SQLite database, computes shortest-path-first routing
table, and outputs RFC 7951 YANG-conformant JSON per isis-rib.yang.
"""

import json
import heapq
import sqlite3
from collections import defaultdict


def is_pseudonode(node_id: str) -> bool:
    """Check if a node ID represents a pseudonode (non-zero pseudonode byte)."""
    return not node_id.endswith(".00")


def node_id_from_lsp_id(lsp_id: str) -> str:
    """Extract node ID (system_id.pseudonode) from an LSP ID.
    LSP ID format: SSSS.SSSS.SSSS.PP-FF -> SSSS.SSSS.SSSS.PP
    """
    return lsp_id.rsplit("-", 1)[0]


def system_id_from_node_id(node_id: str) -> str:
    """Extract system ID from a node ID.
    Node ID: SSSS.SSSS.SSSS.PP -> SSSS.SSSS.SSSS
    """
    return node_id.rsplit(".", 1)[0]


def load_from_sqlite(db_path):
    """Load LSDB data from SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Source router from config table
    cur.execute("SELECT value FROM config WHERE parameter = 'source_router'")
    source_router = cur.fetchone()["value"]

    # LSP header entries
    cur.execute("SELECT lsp_id, remaining_lifetime, overload FROM lsp_entries")
    lsp_rows = cur.fetchall()

    # IS adjacencies (join with lsp_entries implicitly via lsp_id)
    cur.execute("SELECT lsp_id, neighbor_id, metric FROM is_adjacencies")
    adj_rows = cur.fetchall()

    # IPv4 prefix reachability (address and prefix_length are separate columns)
    cur.execute(
        "SELECT lsp_id, address, prefix_length, metric FROM ipv4_prefixes"
    )
    prefix_rows = cur.fetchall()

    conn.close()

    # Build adjacency map: lsp_id -> list of neighbors
    adj_map = defaultdict(list)
    for row in adj_rows:
        adj_map[row["lsp_id"]].append({
            "neighbor_id": row["neighbor_id"],
            "metric": row["metric"],
        })

    # Build prefix map: lsp_id -> list of prefixes (combine address/length)
    prefix_map = defaultdict(list)
    for row in prefix_rows:
        prefix = f"{row['address']}/{row['prefix_length']}"
        prefix_map[row["lsp_id"]].append({
            "prefix": prefix,
            "metric": row["metric"],
        })

    # Assemble LSP records
    lsps = []
    for row in lsp_rows:
        lsp_id = row["lsp_id"]
        lsps.append({
            "lsp_id": lsp_id,
            "remaining_lifetime": row["remaining_lifetime"],
            "overload": bool(row["overload"]),
            "is_neighbors": adj_map.get(lsp_id, []),
            "ipv4_reachability": prefix_map.get(lsp_id, []),
        })

    return source_router, lsps


def build_nodes(lsps):
    """Build aggregated node data from LSPs, skipping expired ones.
    Multiple LSP fragments from the same node are merged.
    """
    nodes = {}
    for lsp in lsps:
        if lsp["remaining_lifetime"] <= 0:
            continue

        node_id = node_id_from_lsp_id(lsp["lsp_id"])

        if node_id not in nodes:
            nodes[node_id] = {
                "is_neighbors": [],
                "ipv4_reachability": [],
                "overload": False,
            }

        node = nodes[node_id]
        node["is_neighbors"].extend(lsp["is_neighbors"])
        node["ipv4_reachability"].extend(lsp["ipv4_reachability"])
        if lsp.get("overload", False):
            node["overload"] = True

    return nodes


def run_spf(source_node, nodes):
    """Run IS-IS SPF (modified Dijkstra) with ECMP tracking.

    Returns:
        cost: dict mapping node_id -> shortest cost from source
        first_hops: dict mapping node_id -> set of first-hop node_ids
    """
    # Identify pseudonodes directly connected to the source
    source_direct_pseudos = set()
    if source_node in nodes:
        for nbr in nodes[source_node]["is_neighbors"]:
            nbr_id = nbr["neighbor_id"]
            if is_pseudonode(nbr_id):
                source_direct_pseudos.add(nbr_id)

    cost = {source_node: 0}
    first_hops = {source_node: set()}
    processed = set()
    pq = [(0, source_node)]

    while pq:
        c, node_id = heapq.heappop(pq)

        if node_id in processed:
            continue
        processed.add(node_id)

        if node_id not in nodes:
            continue

        node = nodes[node_id]

        # Overloaded routers: do NOT expand IS-neighbor links (no transit)
        # Exception: the source router itself
        if node["overload"] and node_id != source_node:
            continue

        for nbr in node["is_neighbors"]:
            nbr_node_id = nbr["neighbor_id"]
            nbr_metric = nbr["metric"]

            # Skip neighbors with no valid LSP
            if nbr_node_id not in nodes:
                continue
            if nbr_node_id in processed:
                continue

            new_cost = c + nbr_metric

            # Compute first-hop for this path
            if node_id == source_node:
                new_fh = {nbr_node_id}
            elif node_id in source_direct_pseudos:
                # Expanding a directly-connected pseudonode:
                # real next-hop is the LAN member, not the pseudonode
                new_fh = {nbr_node_id}
            else:
                new_fh = first_hops[node_id].copy()

            current_cost = cost.get(nbr_node_id, float("inf"))

            if new_cost < current_cost:
                cost[nbr_node_id] = new_cost
                first_hops[nbr_node_id] = new_fh
                heapq.heappush(pq, (new_cost, nbr_node_id))
            elif new_cost == current_cost:
                first_hops[nbr_node_id] |= new_fh

    return cost, first_hops


def build_routing_table(source_node, nodes, cost, first_hops):
    """Build the IPv4 routing table from SPF results.

    For each prefix advertised by any router in the LSDB:
    - total_cost = cost_to_advertising_router + prefix_metric
    - Find minimum total_cost across all advertisers
    - Collect ECMP next-hops from all advertisers at minimum cost
    - Exclude prefixes where the source provides the best cost (connected)
    """
    # Source router's own prefix costs
    source_prefix_costs = {}
    if source_node in nodes:
        for entry in nodes[source_node]["ipv4_reachability"]:
            source_prefix_costs[entry["prefix"]] = 0 + entry["metric"]

    # Best routes from all non-source routers
    prefix_routes = {}

    for node_id, node_data in nodes.items():
        if node_id == source_node:
            continue
        if is_pseudonode(node_id):
            continue
        if node_id not in cost:
            continue

        node_cost = cost[node_id]
        node_fh = first_hops.get(node_id, set())

        for entry in node_data["ipv4_reachability"]:
            prefix = entry["prefix"]
            total = node_cost + entry["metric"]

            if prefix in prefix_routes:
                if total < prefix_routes[prefix]["metric"]:
                    prefix_routes[prefix] = {
                        "metric": total,
                        "next_hops": set(node_fh),
                    }
                elif total == prefix_routes[prefix]["metric"]:
                    prefix_routes[prefix]["next_hops"] |= node_fh
            else:
                prefix_routes[prefix] = {
                    "metric": total,
                    "next_hops": set(node_fh),
                }

    # Filter connected routes and format for YANG output
    routes = []
    for prefix in sorted(prefix_routes.keys()):
        route = prefix_routes[prefix]

        if prefix in source_prefix_costs:
            if source_prefix_costs[prefix] <= route["metric"]:
                continue

        nh_system_ids = sorted(
            {system_id_from_node_id(nh) for nh in route["next_hops"]}
        )

        routes.append({
            "destination-prefix": prefix,
            "total-metric": route["metric"],
            "forwarding-next-hop": nh_system_ids,
        })

    return routes


def main():
    source_router, lsps = load_from_sqlite("/app/isis_lsdb.db")
    source_node = f"{source_router}.00"

    nodes = build_nodes(lsps)
    cost, first_hops = run_spf(source_node, nodes)
    routes = build_routing_table(source_node, nodes, cost, first_hops)

    # RFC 7951 YANG JSON encoding: top-level uses module-name:container-name
    output = {
        "isis-rib:routing-table": {
            "source-router": source_router,
            "route": routes,
        }
    }

    with open("/app/routing_table.json", "w") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    main()
