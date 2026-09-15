"""
MPLS VPN Network Analysis Solver.

Reads from multiple data sources (SQLite, PCAP, JunOS configs, CSV),
computes answers to all queries, writes /app/results.json.

"""

import json
import sqlite3
import struct
import csv
import re
import heapq
import os
from collections import defaultdict


# ═══════════════════════════════════════════════════════════════════
# DATA LOADING: SQLite, PCAP, JunOS configs, CSV
# ═══════════════════════════════════════════════════════════════════

def load_topology_from_db(db_path):
    """Read router and link data from SQLite database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    routers = {}
    for name, loopback, role in c.execute("SELECT name, loopback, role FROM routers"):
        routers[name] = {"loopback": loopback, "role": role}

    links = []
    for r1, r2, metric, bw in c.execute("""
        SELECT ra.name, rb.name, l.metric, l.bandwidth_mbps
        FROM links l
        JOIN routers ra ON l.router_a_id = ra.id
        JOIN routers rb ON l.router_b_id = rb.id
    """):
        links.append({"endpoints": [r1, r2], "metric": metric, "bandwidth_mbps": bw})

    conn.close()
    return routers, links


def load_ldp_from_pcaps(captures_dir):
    """Read LDP label-FEC bindings from PCAP files (one per router)."""
    ldp_labels = {}
    for fname in sorted(os.listdir(captures_dir)):
        if not fname.endswith('.pcap'):
            continue
        router_name = fname[:-5]
        bindings = _parse_pcap(os.path.join(captures_dir, fname))
        ldp_labels[router_name] = bindings
    return ldp_labels


def _parse_pcap(filepath):
    """Parse a pcap file and extract MPLS label -> inner-IP-dst bindings."""
    bindings = {}
    with open(filepath, 'rb') as f:
        # Global header: 24 bytes
        ghdr = f.read(24)
        if len(ghdr) < 24:
            return bindings

        while True:
            phdr = f.read(16)
            if len(phdr) < 16:
                break
            _, _, cap_len, _ = struct.unpack('<IIII', phdr)
            pkt = f.read(cap_len)
            if len(pkt) < cap_len:
                break

            # Ethernet (14 bytes) + MPLS shim (4 bytes) + IP header (20 bytes min)
            if len(pkt) < 38:
                continue
            ethertype = struct.unpack('>H', pkt[12:14])[0]
            if ethertype != 0x8847:
                continue

            mpls_word = struct.unpack('>I', pkt[14:18])[0]
            label = (mpls_word >> 12) & 0xFFFFF

            # Inner IP dst at offset 14 (eth) + 4 (mpls) + 16 (ip dst offset) = 34
            dst_bytes = pkt[34:38]
            fec_ip = '.'.join(str(b) for b in dst_bytes)

            bindings[fec_ip] = label

    return bindings


def load_vrf_configs(configs_dir):
    """Parse JunOS config files to extract VRF import/export RT per PE."""
    pe_vrfs = {}
    for fname in sorted(os.listdir(configs_dir)):
        if not fname.endswith('.conf'):
            continue
        pe_name = fname[:-5]
        pe_vrfs[pe_name] = _parse_junos_config(os.path.join(configs_dir, fname))
    return pe_vrfs


def _parse_junos_config(filepath):
    """Parse a single JunOS config to get VRF -> {import_rt, export_rt}."""
    with open(filepath) as f:
        content = f.read()

    # 1) Community definitions: community <name> members target:<rt>;
    communities = {}
    for m in re.finditer(r'community\s+(\S+)\s+members\s+target:(\S+);', content):
        communities[m.group(1)] = m.group(2)

    # 2) Policy -> RT mapping
    policy_rt = {}
    for m in re.finditer(
        r'policy-statement\s+(\S+)\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}', content
    ):
        ps_name = m.group(1)
        ps_body = m.group(2)
        # Import policy: "from community <name>;"
        fc = re.search(r'from\s+community\s+(\S+);', ps_body)
        if fc and fc.group(1) in communities:
            policy_rt[ps_name] = communities[fc.group(1)]
        # Export policy: "community add <name>;"
        ac = re.search(r'community\s+add\s+(\S+);', ps_body)
        if ac and ac.group(1) in communities:
            policy_rt[ps_name] = communities[ac.group(1)]

    # 3) Routing instances
    vrfs = {}
    ri_match = re.search(r'routing-instances\s*\{', content)
    if not ri_match:
        return vrfs

    # Walk from opening brace, find each VRF block
    start = ri_match.end()
    depth = 1
    i = start
    while i < len(content) and depth > 0:
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
        i += 1
    ri_block = content[start:i - 1]

    # Parse each VRF within routing-instances
    vrf_pos = 0
    while vrf_pos < len(ri_block):
        vm = re.search(r'(\w+)\s*\{', ri_block[vrf_pos:])
        if not vm:
            break
        vrf_name = vm.group(1)
        vs = vrf_pos + vm.end()
        d = 1
        j = vs
        while j < len(ri_block) and d > 0:
            if ri_block[j] == '{':
                d += 1
            elif ri_block[j] == '}':
                d -= 1
            j += 1
        vrf_body = ri_block[vs:j - 1]
        vrf_pos = j

        imp = re.search(r'vrf-import\s+(\S+);', vrf_body)
        exp = re.search(r'vrf-export\s+(\S+);', vrf_body)

        import_rt = []
        export_rt = []
        if imp and imp.group(1) in policy_rt:
            import_rt = [policy_rt[imp.group(1)]]
        if exp and exp.group(1) in policy_rt:
            export_rt = [policy_rt[exp.group(1)]]

        vrfs[vrf_name] = {"import_rt": import_rt, "export_rt": export_rt}

    return vrfs


def load_vpn_routes(csv_path):
    """Read BGP VPNv4 route advertisements from CSV."""
    routes = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            route = {
                "prefix": row["prefix"],
                "originating_pe": row["originating_pe"],
                "vrf": row["vrf"],
                "vpn_label": int(row["vpn_label"]),
                "route_targets": [rt.strip() for rt in row["route_targets"].split(";")],
                "local_pref": int(row["local_pref"]),
                "as_path": row["as_path"],
            }
            if row.get("originator_id", "").strip():
                route["originator_id"] = row["originator_id"].strip()
            routes.append(route)
    return routes


# ═══════════════════════════════════════════════════════════════════
# GRAPH ALGORITHMS
# ═══════════════════════════════════════════════════════════════════

def build_graph(links, min_bw=0):
    graph = defaultdict(list)
    for link in links:
        a, b = link["endpoints"]
        if link["bandwidth_mbps"] >= min_bw:
            graph[a].append((b, link["metric"]))
            graph[b].append((a, link["metric"]))
    return graph


def ip_tuple(ip_str):
    return tuple(int(x) for x in ip_str.split("."))


def dijkstra(graph, src, all_routers):
    dist = {r: float("inf") for r in all_routers}
    prev = {r: [] for r in all_routers}
    dist[src] = 0
    pq = [(0, src)]
    visited = set()

    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        for v, metric in graph[u]:
            nd = d + metric
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = [u]
                heapq.heappush(pq, (nd, v))
            elif nd == dist[v] and u not in prev[v]:
                prev[v].append(u)

    return dist, prev


def get_shortest_path(prev, src, dst, routers):
    if dst == src:
        return [src]
    path = [dst]
    cur = dst
    while cur != src:
        preds = prev[cur]
        if not preds:
            return None
        preds_sorted = sorted(preds, key=lambda r: ip_tuple(routers[r]["loopback"]))
        cur = preds_sorted[0]
        path.append(cur)
    path.reverse()
    return path


def get_all_paths(prev, src, dst):
    if dst == src:
        return [[src]]
    all_paths = []

    def backtrack(node, current_path):
        if node == src:
            all_paths.append(list(reversed(current_path)))
            return
        for p in prev[node]:
            if p not in current_path:
                current_path.append(p)
                backtrack(p, current_path)
                current_path.pop()

    backtrack(dst, [dst])
    all_paths.sort()
    return all_paths


# ═══════════════════════════════════════════════════════════════════
# VRF ROUTE RESOLUTION
# ═══════════════════════════════════════════════════════════════════

def compute_vrf_routes(pe, vrf, pe_vrfs, vpn_routes, routers):
    vrf_config = pe_vrfs.get(pe, {}).get(vrf)
    if not vrf_config:
        return [], {}

    import_rts = set(vrf_config["import_rt"])
    pe_loopback = routers[pe]["loopback"]
    prefixes = {}

    for route in vpn_routes:
        route_rts = set(route["route_targets"])

        # Local CE route
        if (route["originating_pe"] == pe
                and route.get("vrf") == vrf
                and "originator_id" not in route):
            if route["prefix"] not in prefixes:
                prefixes[route["prefix"]] = {
                    "origin": "local",
                    "vpn_label": route["vpn_label"],
                }
            continue

        # Skip own routes (iBGP split-horizon)
        if route["originating_pe"] == pe:
            continue

        # Originator-id loop prevention
        if "originator_id" in route and route["originator_id"] == pe_loopback:
            continue

        # RT match check
        if not route_rts.intersection(import_rts):
            continue

        prefix = route["prefix"]
        if prefix not in prefixes:
            prefixes[prefix] = {
                "origin": "remote",
                "originating_pe": route["originating_pe"],
                "vpn_label": route["vpn_label"],
                "next_hop": routers[route["originating_pe"]]["loopback"],
            }

    return sorted(prefixes.keys()), prefixes


def find_vpn_route_for_prefix(pe, vrf, prefix, pe_vrfs, vpn_routes, routers):
    vrf_config = pe_vrfs.get(pe, {}).get(vrf)
    if not vrf_config:
        return None

    import_rts = set(vrf_config["import_rt"])
    pe_loopback = routers[pe]["loopback"]
    candidates = []

    for route in vpn_routes:
        if route["prefix"] != prefix:
            continue
        route_rts = set(route["route_targets"])

        if (route["originating_pe"] == pe
                and route.get("vrf") == vrf
                and "originator_id" not in route):
            return {"type": "local", "route": route}

        if route["originating_pe"] == pe:
            continue
        if "originator_id" in route and route["originator_id"] == pe_loopback:
            continue
        if not route_rts.intersection(import_rts):
            continue

        candidates.append(route)

    if candidates:
        return {"type": "remote", "route": candidates[0]}
    return None


# ═══════════════════════════════════════════════════════════════════
# MPLS FORWARDING PATH COMPUTATION
# ═══════════════════════════════════════════════════════════════════

def compute_forwarding_path(source_pe, source_vrf, dest_prefix,
                            routers, links, ldp_labels, pe_vrfs, vpn_routes):
    route_info = find_vpn_route_for_prefix(
        source_pe, source_vrf, dest_prefix, pe_vrfs, vpn_routes, routers)
    if not route_info or route_info["type"] == "local":
        return {"hops": []}

    route = route_info["route"]
    egress_pe = route["originating_pe"]
    egress_lo = routers[egress_pe]["loopback"]
    vpn_label = route["vpn_label"]

    all_names = list(routers.keys())
    graph = build_graph(links)
    dist, prev = dijkstra(graph, source_pe, all_names)
    path = get_shortest_path(prev, source_pe, egress_pe, routers)

    if not path or len(path) < 2:
        return {"hops": []}

    hops = []

    # Ingress PE: push [transport, vpn]
    nxt = path[1]
    transport_label = ldp_labels[nxt][egress_lo]
    hops.append({
        "router": source_pe, "action": "push",
        "labels": [transport_label, vpn_label], "forward_to": nxt,
    })

    # Transit routers
    for i in range(1, len(path) - 1):
        cur, nxt = path[i], path[i + 1]
        in_label = ldp_labels[cur][egress_lo]
        out_label = ldp_labels[nxt][egress_lo]
        if out_label == 3:
            hops.append({
                "router": cur, "action": "php",
                "in_label": in_label, "forward_to": nxt,
            })
        else:
            hops.append({
                "router": cur, "action": "swap",
                "in_label": in_label, "out_label": out_label, "forward_to": nxt,
            })

    # Egress PE: dispose vpn label
    hops.append({
        "router": egress_pe, "action": "dispose",
        "in_label": vpn_label, "vrf": source_vrf,
    })

    return {"hops": hops}


def compute_hub_spoke_forwarding(source_pe, source_vrf, dest_prefix,
                                  routers, links, ldp_labels, pe_vrfs, vpn_routes):
    # Find the re-advertised route (points to hub PE)
    route_info = find_vpn_route_for_prefix(
        source_pe, source_vrf, dest_prefix, pe_vrfs, vpn_routes, routers)
    if not route_info or route_info["type"] == "local":
        return {"hops": []}

    route = route_info["route"]
    hub_pe = route["originating_pe"]
    hub_lo = routers[hub_pe]["loopback"]
    hub_vpn_label = route["vpn_label"]

    # Find the original route at the hub (from the actual destination spoke)
    hub_vrf_config = pe_vrfs.get(hub_pe, {}).get(source_vrf)
    if not hub_vrf_config:
        return {"hops": []}
    hub_import_rts = set(hub_vrf_config["import_rt"])

    original_route = None
    for r in vpn_routes:
        if r["prefix"] != dest_prefix:
            continue
        if r["originating_pe"] == hub_pe:
            continue
        if "originator_id" in r:
            continue
        if set(r["route_targets"]).intersection(hub_import_rts):
            original_route = r
            break

    if original_route is None:
        return {"hops": []}

    dest_pe = original_route["originating_pe"]
    dest_lo = routers[dest_pe]["loopback"]
    dest_vpn_label = original_route["vpn_label"]

    all_names = list(routers.keys())
    graph = build_graph(links)
    hops = []

    # ── Leg 1: source spoke → hub ──
    dist1, prev1 = dijkstra(graph, source_pe, all_names)
    path1 = get_shortest_path(prev1, source_pe, hub_pe, routers)
    if not path1 or len(path1) < 2:
        return {"hops": []}

    nxt = path1[1]
    transport_label = ldp_labels[nxt][hub_lo]
    hops.append({
        "router": source_pe, "action": "push",
        "labels": [transport_label, hub_vpn_label], "forward_to": nxt,
    })

    for i in range(1, len(path1) - 1):
        cur, nxt = path1[i], path1[i + 1]
        in_label = ldp_labels[cur][hub_lo]
        out_label = ldp_labels[nxt][hub_lo]
        if out_label == 3:
            hops.append({
                "router": cur, "action": "php",
                "in_label": in_label, "forward_to": nxt,
            })
        else:
            hops.append({
                "router": cur, "action": "swap",
                "in_label": in_label, "out_label": out_label, "forward_to": nxt,
            })

    # ── Hub processing: dispose + re-push ──
    dist2, prev2 = dijkstra(graph, hub_pe, all_names)
    path2 = get_shortest_path(prev2, hub_pe, dest_pe, routers)
    if not path2 or len(path2) < 2:
        return {"hops": []}

    nxt2 = path2[1]
    transport_label2 = ldp_labels[nxt2][dest_lo]
    hops.append({
        "router": hub_pe, "action": "hub_forward",
        "in_label": hub_vpn_label,
        "labels": [transport_label2, dest_vpn_label], "forward_to": nxt2,
    })

    # ── Leg 2: hub → destination spoke ──
    for i in range(1, len(path2) - 1):
        cur, nxt = path2[i], path2[i + 1]
        in_label = ldp_labels[cur][dest_lo]
        out_label = ldp_labels[nxt][dest_lo]
        if out_label == 3:
            hops.append({
                "router": cur, "action": "php",
                "in_label": in_label, "forward_to": nxt,
            })
        else:
            hops.append({
                "router": cur, "action": "swap",
                "in_label": in_label, "out_label": out_label, "forward_to": nxt,
            })

    hops.append({
        "router": dest_pe, "action": "dispose",
        "in_label": dest_vpn_label, "vrf": source_vrf,
    })

    return {"hops": hops}


def is_hub_spoke_query(source_pe, source_vrf, dest_prefix,
                       pe_vrfs, vpn_routes, routers):
    route_info = find_vpn_route_for_prefix(
        source_pe, source_vrf, dest_prefix, pe_vrfs, vpn_routes, routers)
    if not route_info or route_info["type"] == "local":
        return False
    route = route_info["route"]
    return "originator_id" in route


# ═══════════════════════════════════════════════════════════════════
# QUERY PROCESSING
# ═══════════════════════════════════════════════════════════════════

def process_query(query, routers, links, ldp_labels, pe_vrfs, vpn_routes):
    qtype = query["type"]
    all_names = list(routers.keys())

    if qtype == "igp_shortest_path":
        graph = build_graph(links)
        dist, prev = dijkstra(graph, query["source"], all_names)
        path = get_shortest_path(prev, query["source"], query["destination"], routers)
        return {"path": path, "metric": dist[query["destination"]]}

    elif qtype == "igp_ecmp_paths":
        graph = build_graph(links)
        dist, prev = dijkstra(graph, query["source"], all_names)
        paths = get_all_paths(prev, query["source"], query["destination"])
        return {"paths": paths, "metric": dist[query["destination"]]}

    elif qtype == "cspf_path":
        graph = build_graph(links, min_bw=query["min_bandwidth_mbps"])
        dist, prev = dijkstra(graph, query["source"], all_names)
        path = get_shortest_path(prev, query["source"], query["destination"], routers)
        metric = dist[query["destination"]]
        if metric == float("inf"):
            return {"path": None, "metric": None}
        return {"path": path, "metric": metric}

    elif qtype == "vrf_routes":
        prefix_list, _ = compute_vrf_routes(
            query["pe"], query["vrf"], pe_vrfs, vpn_routes, routers)
        return {"prefixes": prefix_list}

    elif qtype == "forwarding_path":
        src_pe = query["source_pe"]
        src_vrf = query["source_vrf"]
        dest_prefix = query["destination_prefix"]

        if is_hub_spoke_query(src_pe, src_vrf, dest_prefix,
                              pe_vrfs, vpn_routes, routers):
            return compute_hub_spoke_forwarding(
                src_pe, src_vrf, dest_prefix,
                routers, links, ldp_labels, pe_vrfs, vpn_routes)
        else:
            return compute_forwarding_path(
                src_pe, src_vrf, dest_prefix,
                routers, links, ldp_labels, pe_vrfs, vpn_routes)

    return {}


def main():
    # Load all data sources
    routers, links = load_topology_from_db("/app/network.db")
    ldp_labels = load_ldp_from_pcaps("/app/captures")
    pe_vrfs = load_vrf_configs("/app/configs")
    vpn_routes = load_vpn_routes("/app/vpn_routes.csv")

    with open("/app/queries.json") as f:
        queries = json.load(f)

    results = {}
    for q in queries["queries"]:
        results[q["id"]] = process_query(
            q, routers, links, ldp_labels, pe_vrfs, vpn_routes)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
