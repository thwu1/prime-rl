#!/usr/bin/env python3
"""
Enterprise Route Computation Engine.
Reads from SQLite database and Cisco IOS config files to compute routing state.
"""

import json
import heapq
import os
import re
import sqlite3
from collections import defaultdict


def query_db(db_path="/app/network.db"):
    """Extract network data from SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    data = {}

    c.execute("SELECT * FROM routers")
    data["routers"] = {r["name"]: dict(r) for r in c.fetchall()}

    c.execute("SELECT * FROM ospf_areas")
    router_areas = defaultdict(list)
    for row in c.fetchall():
        router_areas[row["router"]].append(row["area"])
    for rname in data["routers"]:
        data["routers"][rname]["ospf_areas"] = router_areas.get(rname, [])

    c.execute("SELECT * FROM ospf_links")
    data["ospf_links"] = [dict(r) for r in c.fetchall()]

    c.execute("SELECT * FROM ebgp_sessions")
    data["ebgp_sessions"] = [dict(r) for r in c.fetchall()]

    c.execute("SELECT * FROM bgp_received_routes")
    data["bgp_received_routes"] = [dict(r) for r in c.fetchall()]

    c.execute("SELECT * FROM ibgp_sessions")
    data["ibgp_sessions"] = [dict(r) for r in c.fetchall()]

    c.execute("SELECT * FROM connected_networks")
    data["connected_networks"] = [dict(r) for r in c.fetchall()]

    c.execute("SELECT * FROM admin_distances")
    data["admin_distances"] = {r["protocol"]: r["distance"] for r in c.fetchall()}

    conn.close()
    return data


def parse_configs(config_dir="/app/configs"):
    """Parse Cisco IOS config files for routing policies."""
    configs = {}
    for fname in sorted(os.listdir(config_dir)):
        if not fname.endswith(".cfg"):
            continue
        router = fname.replace(".cfg", "")
        with open(os.path.join(config_dir, fname)) as f:
            text = f.read()
        configs[router] = {
            "route_maps": _parse_route_maps(text),
            "static_routes": _parse_static_routes(text),
            "redistribution": _parse_redistribution(text),
        }
    return configs


def _parse_route_maps(text):
    """Extract route-map definitions from IOS config."""
    route_maps = {}
    current_map = None
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"route-map\s+(\S+)\s+permit\s+(\d+)", line)
        if m:
            current_map = m.group(1)
            if current_map not in route_maps:
                route_maps[current_map] = {}
            continue
        if current_map and line.startswith("set "):
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "local-preference":
                route_maps[current_map]["local_pref"] = int(parts[2])
            elif len(parts) >= 3 and parts[1] == "metric":
                route_maps[current_map]["metric"] = int(parts[2])
            elif len(parts) >= 3 and parts[1] == "metric-type":
                route_maps[current_map]["metric_type"] = parts[2]
        elif current_map and line == "!":
            current_map = None
    return route_maps


def _parse_static_routes(text):
    """Extract static routes from IOS config."""
    routes = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"ip route\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+(\d+))?", line)
        if m:
            network = m.group(1)
            mask = m.group(2)
            next_hop = m.group(3)
            ad = int(m.group(4)) if m.group(4) else 1
            prefix_len = sum(bin(int(x)).count("1") for x in mask.split("."))
            routes.append({
                "prefix": f"{network}/{prefix_len}",
                "next_hop": next_hop.lower(),
                "admin_distance": ad,
            })
    return routes


def _parse_redistribution(text):
    """Extract redistribution config from IOS config."""
    redist = []
    route_maps = _parse_route_maps(text)
    for line in text.splitlines():
        line = line.strip()
        if "redistribute connected" in line:
            m = re.search(r"route-map\s+(\S+)", line)
            rm_name = m.group(1) if m else None
            metric = 20
            metric_type = "type-2"
            if rm_name and rm_name in route_maps:
                rm = route_maps[rm_name]
                metric = rm.get("metric", 20)
                metric_type = rm.get("metric_type", "type-2")
            redist.append({
                "from": "connected",
                "into": "ospf",
                "route_map": rm_name,
                "metric": metric,
                "metric_type": metric_type,
            })
    return redist


def dijkstra(graph, source):
    """Shortest-path computation on a weighted graph."""
    dist = {source: 0}
    prev = {}
    pq = [(0, source)]
    visited = set()

    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        for v, w in graph.get(u, []):
            if v not in visited:
                nd = d + w
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))

    return dist, prev


def get_next_hop_ip(links, src, first_hop_router):
    """Return the IP of first_hop_router on the link shared with src."""
    for link in links:
        if link["router_a"] == src and link["router_b"] == first_hop_router:
            return link["ip_b"]
        if link["router_b"] == src and link["router_a"] == first_hop_router:
            return link["ip_a"]
    return "unknown"


def compute_ospf(db_data):
    """Compute OSPF costs between all router pairs."""
    routers = db_data["routers"]
    links = db_data["ospf_links"]

    area_graphs = defaultdict(lambda: defaultdict(list))
    area_routers_set = defaultdict(set)

    for link in links:
        a, b = link["router_a"], link["router_b"]
        cost = link["cost"]
        area = link["area"]
        area_graphs[area][a].append((b, cost))
        area_graphs[area][b].append((a, cost))
        area_routers_set[area].add(a)
        area_routers_set[area].add(b)

    costs = defaultdict(dict)
    first_hops = defaultdict(dict)

    for area, graph in area_graphs.items():
        for router in area_routers_set[area]:
            dist, prev = dijkstra(dict(graph), router)
            for dest, cost in dist.items():
                if dest == router:
                    continue
                if dest not in costs[router] or cost < costs[router][dest]:
                    costs[router][dest] = cost
                    hop = dest
                    while prev.get(hop) != router:
                        hop = prev[hop]
                    first_hops[router][dest] = hop

    abrs = [r for r, d in routers.items() if len(d["ospf_areas"]) > 1]

    for _ in range(len(routers)):
        changed = False
        for abr in abrs:
            for dest in list(routers.keys()):
                if dest == abr or dest not in costs[abr]:
                    continue
                abr_cost = costs[abr][dest]
                for area in routers[abr]["ospf_areas"]:
                    for router in area_routers_set[area]:
                        if router == abr or router == dest:
                            continue
                        if abr not in costs[router]:
                            continue
                        total = costs[router][abr] + abr_cost
                        if dest not in costs[router] or total < costs[router][dest]:
                            costs[router][dest] = total
                            first_hops[router][dest] = first_hops[router][abr]
                            changed = True
        if not changed:
            break

    return dict(costs), dict(first_hops)


ORIGIN_RANK = {"igp": 0, "egp": 1, "incomplete": 2}


def _bgp_compare(a, b):
    """Compare two BGP paths. Returns (winner, decision_step)."""
    if a["weight"] != b["weight"]:
        return (a, "weight") if a["weight"] > b["weight"] else (b, "weight")
    if a["local_pref"] != b["local_pref"]:
        return (a, "local_pref") if a["local_pref"] > b["local_pref"] else (b, "local_pref")
    if len(a["as_path"]) != len(b["as_path"]):
        return (a, "as_path_length") if len(a["as_path"]) < len(b["as_path"]) else (b, "as_path_length")
    oa, ob = ORIGIN_RANK[a["origin"]], ORIGIN_RANK[b["origin"]]
    if oa != ob:
        return (a, "origin") if oa < ob else (b, "origin")
    if a["peer_as"] == b["peer_as"] and a["med"] != b["med"]:
        return (a, "med") if a["med"] < b["med"] else (b, "med")
    if a["source"] != b["source"]:
        return (a, "ebgp_over_ibgp") if a["source"] == "ebgp" else (b, "ebgp_over_ibgp")
    return (a, "router_id")


def _select_best(candidates):
    """BGP best-path selection; returns (winning_path, decision_step)."""
    best = candidates[0]
    win_reason = "default"

    for other in candidates[1:]:
        winner, reason = _bgp_compare(best, other)
        if winner is other:
            best = other
            win_reason = reason

    for other in candidates:
        if other is best:
            continue
        _, win_reason = _bgp_compare(best, other)
        break

    return best, win_reason


def compute_bgp(db_data, configs):
    """BGP best path selection."""
    routers = db_data["routers"]
    ebgp_sessions = db_data["ebgp_sessions"]
    ibgp_sessions = db_data["ibgp_sessions"]
    bgp_routes = db_data["bgp_received_routes"]

    bgp_speakers = [r for r, d in routers.items() if d["is_bgp_speaker"]]

    session_map = {s["id"]: s for s in ebgp_sessions}

    bgp_tables = defaultdict(lambda: defaultdict(list))

    for route in bgp_routes:
        sess = session_map[route["session_id"]]
        local = sess["local_router"]

        rm_name = sess["route_map_in"]
        local_pref = 100
        if rm_name and local in configs:
            rm = configs[local]["route_maps"].get(rm_name, {})
            local_pref = rm.get("local_pref", 100)

        bgp_tables[local][route["prefix"]].append({
            "prefix": route["prefix"],
            "as_path": json.loads(route["as_path"]),
            "origin": route["origin"],
            "med": route["med"],
            "local_pref": local_pref,
            "weight": 0,
            "next_hop": sess["remote_ip"],
            "source": "ebgp",
            "source_router": sess["isp_name"],
            "peer_as": sess["remote_as"],
        })

    for sess in ibgp_sessions:
        ra, rb = sess["router_a"], sess["router_b"]
        for src, dst in [(ra, rb), (rb, ra)]:
            for prefix, paths in list(bgp_tables[src].items()):
                for p in paths:
                    if p["source"] != "ebgp":
                        continue
                    ibgp_path = dict(p)
                    ibgp_path["source"] = "ibgp"
                    ibgp_path["source_router"] = src
                    if sess["next_hop_self"]:
                        ibgp_path["next_hop"] = routers[src]["loopback_ip"]
                    bgp_tables[dst][prefix].append(ibgp_path)

    best_paths = {}
    for router in bgp_speakers:
        best_paths[router] = {}
        for prefix, candidates in bgp_tables[router].items():
            if len(candidates) == 1:
                bp = candidates[0]
                reason = "only_path"
            else:
                bp, reason = _select_best(candidates)

            best_paths[router][prefix] = {
                "selected_via": bp["source"],
                "selected_from": bp["source_router"],
                "as_path": bp["as_path"],
                "local_pref": bp["local_pref"],
                "origin": bp["origin"],
                "med": bp["med"],
                "next_hop": bp["next_hop"],
                "decision_reason": reason,
            }

    return best_paths


def compute_rib(db_data, configs, ospf_costs, ospf_hops, bgp_best):
    """Build the RIB for each router."""
    routers = db_data["routers"]
    links = db_data["ospf_links"]
    ad = db_data["admin_distances"]
    connected_nets = db_data["connected_networks"]
    rib = {r: {} for r in routers}

    for rname in routers:
        entries = rib[rname]
        rdata = routers[rname]

        # Connected: loopback
        entries[f"{rdata['loopback_ip']}/32"] = {
            "protocol": "connected", "admin_distance": 0, "metric": 0, "next_hop": "connected"
        }

        # Connected: OSPF link networks
        for link in links:
            if rname in (link["router_a"], link["router_b"]):
                entries[link["network"]] = {
                    "protocol": "connected", "admin_distance": 0, "metric": 0, "next_hop": "connected"
                }

        # Connected: eBGP peering links
        for sess in db_data["ebgp_sessions"]:
            if sess["local_router"] == rname:
                entries[sess["link_network"]] = {
                    "protocol": "connected", "admin_distance": 0, "metric": 0, "next_hop": "connected"
                }

        # Connected: extra networks
        for cn in connected_nets:
            if cn["router"] == rname:
                entries[cn["network"]] = {
                    "protocol": "connected", "admin_distance": 0, "metric": 0, "next_hop": "connected"
                }

        # Static routes (from configs)
        if rname in configs:
            for route in configs[rname]["static_routes"]:
                pfx = route["prefix"]
                route_ad = route["admin_distance"]
                cur = entries.get(pfx)
                if cur is None or route_ad < cur["admin_distance"]:
                    entries[pfx] = {
                        "protocol": "static",
                        "admin_distance": route_ad,
                        "metric": 0,
                        "next_hop": route["next_hop"],
                    }

        # OSPF routes to other routers' loopbacks
        for dname, ddata in routers.items():
            if dname == rname:
                continue
            cost = (ospf_costs.get(rname) or {}).get(dname)
            if cost is None:
                continue
            pfx = f"{ddata['loopback_ip']}/32"
            cur = entries.get(pfx)
            if cur is None or ad["ospf"] < cur["admin_distance"]:
                nh_rtr = (ospf_hops.get(rname) or {}).get(dname)
                nh_ip = get_next_hop_ip(links, rname, nh_rtr) if nh_rtr else "unknown"
                entries[pfx] = {
                    "protocol": "ospf",
                    "admin_distance": ad["ospf"],
                    "metric": cost,
                    "next_hop": nh_ip,
                }

        # OSPF routes to transit link networks
        for link in links:
            if rname in (link["router_a"], link["router_b"]):
                continue
            pfx = link["network"]
            ca = (ospf_costs.get(rname) or {}).get(link["router_a"], float("inf"))
            cb = (ospf_costs.get(rname) or {}).get(link["router_b"], float("inf"))
            if ca <= cb and ca < float("inf"):
                near = link["router_a"]
                best_c = ca
            elif cb < float("inf"):
                near = link["router_b"]
                best_c = cb
            else:
                continue
            cur = entries.get(pfx)
            if cur is None or ad["ospf"] < cur["admin_distance"]:
                nh_rtr = (ospf_hops.get(rname) or {}).get(near)
                nh_ip = get_next_hop_ip(links, rname, nh_rtr) if nh_rtr else "unknown"
                entries[pfx] = {
                    "protocol": "ospf",
                    "admin_distance": ad["ospf"],
                    "metric": best_c,
                    "next_hop": nh_ip,
                }

        # OSPF E2 (redistribution from configs)
        for cfg_router, cfg in configs.items():
            for redist in cfg.get("redistribution", []):
                if redist["from"] != "connected" or redist["into"] != "ospf":
                    continue
                asbr = cfg_router
                metric = redist["metric"]
                if redist["metric_type"] != "type-2":
                    continue
                for cn in connected_nets:
                    if cn["router"] != asbr:
                        continue
                    subnet = cn["network"]
                    cur = entries.get(subnet)
                    if cur is not None and cur["admin_distance"] <= ad["ospf"]:
                        continue
                    if asbr == rname:
                        continue
                    cost_to_asbr = (ospf_costs.get(rname) or {}).get(asbr)
                    if cost_to_asbr is None:
                        continue
                    nh_rtr = (ospf_hops.get(rname) or {}).get(asbr)
                    nh_ip = get_next_hop_ip(links, rname, nh_rtr) if nh_rtr else "unknown"
                    entries[subnet] = {
                        "protocol": "ospf_e2",
                        "admin_distance": ad["ospf"],
                        "metric": metric,
                        "next_hop": nh_ip,
                    }

        # BGP routes
        if rname in bgp_best:
            for pfx, bp in bgp_best[rname].items():
                bgp_ad = ad["ebgp"] if bp["selected_via"] == "ebgp" else ad["ibgp"]
                cur = entries.get(pfx)
                if cur is None or bgp_ad < cur["admin_distance"]:
                    entries[pfx] = {
                        "protocol": bp["selected_via"],
                        "admin_distance": bgp_ad,
                        "metric": 0,
                        "next_hop": bp["next_hop"],
                    }

    return rib


def detect_issues(db_data, configs, ospf_costs, bgp_best, rib):
    """Identify routing anomalies."""
    issues = []
    connected_nets = db_data["connected_networks"]

    # Static routes shadowing OSPF externals
    for rname, cfg in configs.items():
        for route in cfg["static_routes"]:
            prefix = route["prefix"]
            for cfg_r, cfg_d in configs.items():
                for redist in cfg_d.get("redistribution", []):
                    for cn in connected_nets:
                        if cn["router"] == cfg_r and cn["network"] == prefix:
                            asbr = cfg_r
                            if (ospf_costs.get(rname) or {}).get(asbr) is not None:
                                issues.append({
                                    "type": "route_shadowing",
                                    "router": rname,
                                    "prefix": prefix,
                                    "description": (
                                        f"Static route to {route['next_hop']} (AD {route['admin_distance']}) "
                                        f"shadows OSPF E2 route via {asbr} (AD 110). "
                                        f"Traffic to {prefix} is blackholed via null0 "
                                        f"instead of being routed through OSPF to {asbr}."
                                    ),
                                })

    # BGP suboptimality
    for sess in db_data["ebgp_sessions"]:
        router = sess["local_router"]
        for route in db_data["bgp_received_routes"]:
            if route["session_id"] != sess["id"]:
                continue
            prefix = route["prefix"]
            bp = (bgp_best.get(router) or {}).get(prefix)
            if bp and bp["selected_via"] == "ibgp":
                rm_name = sess["route_map_in"]
                ebgp_lp = 100
                if rm_name and router in configs:
                    rm = configs[router]["route_maps"].get(rm_name, {})
                    ebgp_lp = rm.get("local_pref", 100)
                issues.append({
                    "type": "bgp_suboptimal_path",
                    "router": router,
                    "prefix": prefix,
                    "description": (
                        f"BGP selects iBGP path (local_pref {bp['local_pref']}) over locally available "
                        f"eBGP path (local_pref {ebgp_lp}). "
                        f"The eBGP path would have AD 20 but BGP's best-path algorithm prefers the iBGP "
                        f"path (AD 200) due to higher local-pref, resulting in suboptimal forwarding."
                    ),
                })

    return issues


def main():
    db_data = query_db()
    configs = parse_configs()

    ospf_costs, ospf_hops = compute_ospf(db_data)
    bgp_best = compute_bgp(db_data, configs)
    rib = compute_rib(db_data, configs, ospf_costs, ospf_hops, bgp_best)
    issues = detect_issues(db_data, configs, ospf_costs, bgp_best, rib)

    os.makedirs("/app/output", exist_ok=True)

    for name, data in [
        ("ospf_costs.json", ospf_costs),
        ("bgp_best_paths.json", bgp_best),
        ("rib.json", rib),
        ("issues.json", issues),
    ]:
        with open(f"/app/output/{name}", "w") as f:
            json.dump(data, f, indent=2)

    print("Route computation complete. Outputs written to /app/output/")


if __name__ == "__main__":
    main()
