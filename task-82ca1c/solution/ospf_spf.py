#!/usr/bin/env python3
"""
OSPF SPF Routing Table Computation per RFC 2328 Section 16.

Reads LSDB from /app/ospf.db (SQLite) and /app/summary_lsas.bin (binary),
computes the routing table, writes to /app/results/routing_table.json.
"""

import json
import heapq
import ipaddress
import os
import sqlite3
import struct
import socket
from collections import defaultdict

_DIRECT = "__DIRECT__"


def mask_to_prefixlen(mask):
    return sum(bin(int(o)).count("1") for o in mask.split("."))


def to_cidr(ip, mask):
    plen = mask_to_prefixlen(mask)
    net = ipaddress.IPv4Network(f"{ip}/{plen}", strict=False)
    return str(net)


def bytes_to_ip(b):
    return socket.inet_ntoa(b)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_lsdb_from_sqlite(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT value FROM metadata WHERE key='compute_router'")
    compute_router = c.fetchone()['value']
    c.execute("SELECT value FROM metadata WHERE key='backbone_area'")
    backbone_area = c.fetchone()['value']

    # Router-LSAs
    router_lsas = {}
    c.execute("SELECT * FROM router_lsas WHERE area_id=?", (backbone_area,))
    for row in c.fetchall():
        adv = row['advertising_router']
        router_lsas[adv] = {
            'advertising_router': adv,
            'lsa_id': row['lsa_id'],
            'sequence_number': row['sequence_number'],
            'age': row['age'],
            'flags': {
                'b': bool(row['flag_abr']),
                'e': bool(row['flag_asbr']),
                'v': bool(row['flag_virtual']),
            },
            'links': [],
        }

    c.execute(
        "SELECT * FROM router_links WHERE area_id=? "
        "ORDER BY advertising_router, seq",
        (backbone_area,),
    )
    for row in c.fetchall():
        adv = row['advertising_router']
        if adv in router_lsas:
            router_lsas[adv]['links'].append({
                'type': row['link_type'],
                'link_id': row['link_id'],
                'link_data': row['link_data'],
                'metric': row['metric'],
            })

    # Network-LSAs
    network_lsas = {}
    c.execute("SELECT * FROM network_lsas WHERE area_id=?", (backbone_area,))
    for row in c.fetchall():
        lid = row['lsa_id']
        network_lsas[lid] = {
            'lsa_id': lid,
            'advertising_router': row['advertising_router'],
            'network_mask': row['network_mask'],
            'attached_routers': [],
        }

    c.execute(
        "SELECT * FROM network_attached_routers WHERE area_id=? "
        "ORDER BY network_lsa_id, seq",
        (backbone_area,),
    )
    for row in c.fetchall():
        nlid = row['network_lsa_id']
        if nlid in network_lsas:
            network_lsas[nlid]['attached_routers'].append(row['router_id'])

    conn.close()
    return compute_router, router_lsas, network_lsas


def load_summary_lsas_from_binary(file_path):
    with open(file_path, 'rb') as f:
        data = f.read()

    assert data[:4] == b'OSPF', "Invalid magic"
    assert data[4] == 0x01, "Unsupported version"

    count = struct.unpack('!H', data[9:11])[0]

    summary_lsas = []
    offset = 11
    for _ in range(count):
        lsa_id = bytes_to_ip(data[offset:offset + 4])
        adv_router = bytes_to_ip(data[offset + 4:offset + 8])
        seq_num = struct.unpack('!I', data[offset + 8:offset + 12])[0]
        age = struct.unpack('!H', data[offset + 12:offset + 14])[0]
        mask = bytes_to_ip(data[offset + 14:offset + 18])
        metric = struct.unpack('!I', b'\x00' + data[offset + 18:offset + 21])[0]

        summary_lsas.append({
            'lsa_type': 3,
            'lsa_id': lsa_id,
            'advertising_router': adv_router,
            'sequence_number': f"0x{seq_num:08x}",
            'age': age,
            'network_mask': mask,
            'metric': metric,
        })
        offset += 21

    return summary_lsas


# ---------------------------------------------------------------------------
# SPF computation (RFC 2328 Section 16.1)
# ---------------------------------------------------------------------------

def run_spf(root_id, router_lsas, network_lsas):
    INF = float("inf")
    dist = {}
    nexthops = defaultdict(set)
    on_tree = set()

    root_key = (root_id, "R")
    dist[root_key] = 0
    heap = [(0, root_id, "R")]

    while heap:
        d, vid, vtype = heapq.heappop(heap)
        vkey = (vid, vtype)
        if vkey in on_tree:
            continue
        if d > dist.get(vkey, INF):
            continue
        on_tree.add(vkey)

        if vtype == "R":
            lsa = router_lsas.get(vid)
            if not lsa:
                continue
            for link in lsa["links"]:
                ltype = link["type"]
                if ltype == 1:
                    neighbor_id = link["link_id"]
                    wkey = (neighbor_id, "R")
                    new_d = d + link["metric"]
                    if wkey in on_tree:
                        continue
                    if vkey == root_key:
                        w_nh = set()
                        nlsa = router_lsas.get(neighbor_id)
                        if nlsa:
                            for nl in nlsa["links"]:
                                if nl["type"] == 1 and nl["link_id"] == root_id:
                                    w_nh = {nl["link_data"]}
                                    break
                    else:
                        w_nh = set(nexthops[vkey])
                    if new_d < dist.get(wkey, INF):
                        dist[wkey] = new_d
                        nexthops[wkey] = w_nh
                        heapq.heappush(heap, (new_d, neighbor_id, "R"))
                    elif new_d == dist.get(wkey, INF):
                        nexthops[wkey] |= w_nh

                elif ltype == 2:
                    dr_ip = link["link_id"]
                    wkey = (dr_ip, "N")
                    new_d = d + link["metric"]
                    if wkey in on_tree or dr_ip not in network_lsas:
                        continue
                    if vkey == root_key:
                        w_nh = {_DIRECT}
                    else:
                        w_nh = set(nexthops[vkey])
                    if new_d < dist.get(wkey, INF):
                        dist[wkey] = new_d
                        nexthops[wkey] = w_nh
                        heapq.heappush(heap, (new_d, dr_ip, "N"))
                    elif new_d == dist.get(wkey, INF):
                        nexthops[wkey] |= w_nh

        elif vtype == "N":
            nlsa = network_lsas.get(vid)
            if not nlsa:
                continue
            root_direct = _DIRECT in nexthops[vkey]
            for attached_router in nlsa["attached_routers"]:
                wkey = (attached_router, "R")
                new_d = d
                if wkey in on_tree:
                    continue
                if root_direct:
                    w_nh = set()
                    rlsa = router_lsas.get(attached_router)
                    if rlsa:
                        for rl in rlsa["links"]:
                            if rl["type"] == 2 and rl["link_id"] == vid:
                                w_nh = {rl["link_data"]}
                                break
                else:
                    w_nh = set(nexthops[vkey])
                if new_d < dist.get(wkey, INF):
                    dist[wkey] = new_d
                    nexthops[wkey] = w_nh
                    heapq.heappush(heap, (new_d, attached_router, "R"))
                elif new_d == dist.get(wkey, INF):
                    nexthops[wkey] |= w_nh

    return dist, nexthops, on_tree


# ---------------------------------------------------------------------------
# Routing table assembly
# ---------------------------------------------------------------------------

def compute_routing_table(compute_router, router_lsas, network_lsas,
                          summary_lsas):
    root_id = compute_router
    dist, nexthops, on_tree = run_spf(root_id, router_lsas, network_lsas)

    # Identify root's connected subnets (to exclude from output)
    connected = set()
    root_lsa = router_lsas[root_id]
    for link in root_lsa["links"]:
        if link["type"] == 3:
            connected.add(to_cidr(link["link_id"], link["link_data"]))

    routes = {}

    # Intra-area: stub links from tree routers + transit network destinations
    for (vid, vtype) in on_tree:
        if vtype == "R":
            lsa = router_lsas.get(vid)
            if not lsa:
                continue
            for link in lsa["links"]:
                if link["type"] != 3:
                    continue
                dest = to_cidr(link["link_id"], link["link_data"])
                cost = dist[(vid, "R")] + link["metric"]
                nh = [] if vid == root_id else sorted(nexthops[(vid, "R")])
                if dest not in routes or cost < routes[dest]["metric"]:
                    routes[dest] = {
                        "metric": cost,
                        "route_type": "intra-area",
                        "next_hops": list(nh),
                    }
                elif (cost == routes[dest]["metric"]
                      and routes[dest]["route_type"] == "intra-area"):
                    merged = sorted(set(routes[dest]["next_hops"]) | set(nh))
                    routes[dest]["next_hops"] = merged

        elif vtype == "N":
            nlsa = network_lsas.get(vid)
            if not nlsa:
                continue
            dest = to_cidr(vid, nlsa["network_mask"])
            cost = dist[(vid, "N")]
            nh = sorted(h for h in nexthops[(vid, "N")] if h != _DIRECT)
            if dest not in routes or cost < routes[dest]["metric"]:
                routes[dest] = {
                    "metric": cost,
                    "route_type": "intra-area",
                    "next_hops": nh if nh else [],
                }
            elif (cost == routes[dest]["metric"]
                  and routes[dest]["route_type"] == "intra-area"):
                merged = sorted(set(routes[dest]["next_hops"]) | set(nh))
                routes[dest]["next_hops"] = merged

    # Remove connected routes
    for subnet in connected:
        routes.pop(subnet, None)

    # Inter-area: Summary-LSAs from reachable ABRs
    for slsa in summary_lsas:
        adv_router = slsa["advertising_router"]
        adv_key = (adv_router, "R")
        if adv_key not in on_tree:
            continue
        adv_lsa = router_lsas.get(adv_router)
        if not adv_lsa or not adv_lsa["flags"].get("b", False):
            continue
        dest = to_cidr(slsa["lsa_id"], slsa["network_mask"])
        cost = dist[adv_key] + slsa["metric"]
        if dest in routes and routes[dest]["route_type"] == "intra-area":
            continue
        nh = sorted(nexthops[adv_key])
        if dest not in routes or cost < routes[dest]["metric"]:
            routes[dest] = {
                "metric": cost,
                "route_type": "inter-area",
                "next_hops": list(nh),
            }
        elif (cost == routes[dest]["metric"]
              and routes[dest]["route_type"] == "inter-area"):
            merged = sorted(set(routes[dest]["next_hops"]) | set(nh))
            routes[dest]["next_hops"] = merged

    result = []
    for dest in sorted(routes, key=lambda x: ipaddress.IPv4Network(x)):
        r = routes[dest]
        result.append({
            "destination": dest,
            "metric": r["metric"],
            "route_type": r["route_type"],
            "next_hops": r["next_hops"],
        })
    return result


def main():
    compute_router, router_lsas, network_lsas = load_lsdb_from_sqlite(
        "/app/ospf.db"
    )
    summary_lsas = load_summary_lsas_from_binary("/app/summary_lsas.bin")

    routing_table = compute_routing_table(
        compute_router, router_lsas, network_lsas, summary_lsas
    )

    os.makedirs("/app/results", exist_ok=True)
    with open("/app/results/routing_table.json", "w") as f:
        json.dump(routing_table, f, indent=2)

    print(f"Computed {len(routing_table)} routes:")
    for r in routing_table:
        print(
            f"  {r['destination']:18s}  metric={r['metric']:3d}  "
            f"{r['route_type']:11s}  NH={r['next_hops']}"
        )


if __name__ == "__main__":
    main()
