#!/usr/bin/env python3
"""OSPF Multi-Area Route Computation Engine.

Reads link costs from tshark pcap extraction, topology from SQLite,
queries from XSLT-transformed XML, computes routing tables, writes JSON.
"""

import json
import sqlite3
import heapq
import re
import xml.etree.ElementTree as ET
from collections import defaultdict


def extract_pcap_costs(json_path):
    """Parse tshark JSON output to extract OSPF adjacency costs.

    Looks for syslog OSPF-ADJ messages with state=FULL and extracts
    the link cost, source router (hostname), and neighbor router.
    """
    with open(json_path) as f:
        packets = json.load(f)

    link_costs = {}

    for pkt in packets:
        layers = pkt.get('_source', {}).get('layers', {})

        msg = ''

        # Try syslog dissector output first
        syslog_layer = layers.get('syslog', {})
        if syslog_layer:
            raw = syslog_layer.get('syslog.msg', '')
            if isinstance(raw, list):
                msg = raw[0] if raw else ''
            else:
                msg = raw or ''

        # Fallback: decode raw data layer (hex-encoded payload)
        if not msg:
            data_layer = layers.get('data', {})
            raw_hex = data_layer.get('data.data', '')
            if isinstance(raw_hex, list):
                raw_hex = raw_hex[0] if raw_hex else ''
            if raw_hex:
                try:
                    msg = bytes.fromhex(
                        raw_hex.replace(':', '')
                    ).decode('ascii', errors='ignore')
                except (ValueError, UnicodeDecodeError):
                    continue

        if 'OSPF-ADJ' not in msg or 'state=FULL' not in msg:
            continue

        # Strip <PRI> prefix if present (raw data decode case)
        if msg.startswith('<'):
            idx = msg.find('>')
            if idx > 0:
                msg = msg[idx + 1:]

        # Parse key=value pairs from the message
        kv = {}
        for token in msg.split():
            if '=' in token:
                k, v = token.split('=', 1)
                kv[k] = v

        # Extract hostname: 4th whitespace-separated token
        # Format: Mmm DD HH:MM:SS HOSTNAME TAG[PID]: ...
        tokens = msg.split(None, 4)
        hostname = tokens[3] if len(tokens) >= 4 else ''

        neighbor = kv.get('neighbor-name', '')
        cost_str = kv.get('cost', '0')
        area_str = kv.get('area', '0')

        if hostname and neighbor and cost_str != '0':
            key = tuple(sorted([hostname, neighbor]))
            link_costs[key] = {
                'cost': int(cost_str),
                'area': int(area_str),
            }

    return link_costs


def load_topology(db_path, pcap_costs):
    """Load topology from SQLite, merging NULL costs with pcap data."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    routers = {}
    for row in c.execute('SELECT id, loopback, area, type, areas FROM routers'):
        rid = row['id']
        routers[rid] = {
            'loopback': row['loopback'],
            'area': row['area'],
            'type': row['type'],
        }
        if row['areas']:
            routers[rid]['areas'] = [int(a) for a in row['areas'].split(',')]

    links = []
    for row in c.execute('SELECT endpoint1, endpoint2, cost, area FROM links'):
        cost = row['cost']
        r1, r2 = row['endpoint1'], row['endpoint2']

        # Fill NULL costs from pcap extraction
        if cost is None:
            key = tuple(sorted([r1, r2]))
            if key in pcap_costs:
                cost = pcap_costs[key]['cost']
            else:
                raise ValueError(
                    "Missing cost for link %s-%s not found in pcap" % (r1, r2))

        links.append({
            'endpoints': [r1, r2],
            'cost': cost,
            'area': row['area'],
        })

    areas = {}
    for row in c.execute('SELECT id, type, default_cost FROM areas'):
        entry = {'type': row['type']}
        if row['default_cost'] is not None:
            entry['default_cost'] = row['default_cost']
        areas[str(row['id'])] = entry

    externals = []
    for row in c.execute(
            'SELECT asbr, prefix, metric_type, metric FROM external_routes'):
        externals.append({
            'asbr': row['asbr'],
            'prefix': row['prefix'],
            'metric_type': row['metric_type'],
            'metric': row['metric'],
        })

    conn.close()
    return {
        'routers': routers,
        'links': links,
        'areas': areas,
        'external_routes': externals,
    }


def load_queries(xml_path):
    """Load queries from XSLT-transformed XML."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    queries = []
    for q in root.find('query-set').findall('query'):
        queries.append({
            'router': q.get('router'),
            'destination': q.get('destination'),
        })
    return queries


def dijkstra(adj, source):
    """Single-source shortest path using Dijkstra's algorithm."""
    dist = {source: 0}
    first_hop = {source: source}
    counter = 0
    pq = [(0, counter, source)]
    visited = set()
    while pq:
        d, _, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        for v, w in adj.get(u, []):
            nd = d + w
            if v not in dist or nd < dist[v]:
                dist[v] = nd
                first_hop[v] = v if u == source else first_hop[u]
                counter += 1
                heapq.heappush(pq, (nd, counter, v))
    return {n: (dist[n], first_hop[n]) for n in dist if n != source}


def get_areas(rid, routers):
    info = routers[rid]
    return info.get('areas', [info['area']])


def compute_routes(topo):
    """Full OSPF route computation pipeline."""
    routers = topo['routers']
    links = topo['links']
    areas_cfg = topo['areas']
    externals = topo['external_routes']

    # Build per-area adjacency lists
    area_adj = defaultdict(lambda: defaultdict(list))
    for lnk in links:
        a = lnk['area']
        r1, r2 = lnk['endpoints']
        area_adj[a][r1].append((r2, lnk['cost']))
        area_adj[a][r2].append((r1, lnk['cost']))
    for rid in routers:
        for a in get_areas(rid, routers):
            area_adj[a].setdefault(rid, [])

    # Per-area SPF
    spf = {}
    for a in area_adj:
        spf[a] = {}
        for src in area_adj[a]:
            spf[a][src] = dijkstra(dict(area_adj[a]), src)

    # Routing table
    rt = defaultdict(dict)

    TYPE_PREF = {
        "O": 0, "O IA": 1, "O*IA": 1,
        "O N1": 2, "O E1": 2,
        "O N2": 3, "O*N2": 3, "O E2": 3,
    }

    def install(router, pfx, cost, nh, rtype, fwd=None):
        p = TYPE_PREF.get(rtype, 99)
        ex = rt[router].get(pfx)
        if ex:
            ep = TYPE_PREF.get(ex['type'], 99)
            if p > ep:
                return
            if p == ep:
                if rtype in ("O E2", "O N2", "O*N2"):
                    if cost > ex['cost']:
                        return
                    if cost == ex['cost']:
                        if (fwd or 999999) >= ex.get('forward_cost', 999999):
                            return
                else:
                    if cost >= ex['cost']:
                        return
        entry = {"cost": cost, "next_hop": nh, "type": rtype}
        if fwd is not None:
            entry["forward_cost"] = fwd
        rt[router][pfx] = entry

    # Phase 1: Own loopbacks
    for rid in routers:
        install(rid, routers[rid]['loopback'], 0, rid, "O")

    # Phase 2: Intra-area routes
    for rid in routers:
        for a in get_areas(rid, routers):
            if a in spf and rid in spf[a]:
                for dest_r, (c, nh) in spf[a][rid].items():
                    if routers[dest_r]['area'] == a:
                        install(rid, routers[dest_r]['loopback'], c, nh, "O")

    # Phase 3: Inter-area routes
    abrs = [r for r in routers if routers[r].get('type') == 'ABR']
    pfx_area = {routers[r]['loopback']: routers[r]['area'] for r in routers}

    # Type 3 LSAs into backbone
    t3_a0 = defaultdict(list)
    for abr in abrs:
        for a in get_areas(abr, routers):
            if a == 0:
                continue
            if a in spf and abr in spf[a]:
                for dr, (c, _) in spf[a][abr].items():
                    if routers[dr]['area'] == a:
                        t3_a0[routers[dr]['loopback']].append((abr, c))

    # Install inter-area routes for backbone routers
    for rid in routers:
        if 0 not in get_areas(rid, routers):
            continue
        for pfx, ads in t3_a0.items():
            for abr, m in ads:
                if abr == rid:
                    continue
                if 0 in spf and rid in spf[0] and abr in spf[0][rid]:
                    ca, nh = spf[0][rid][abr]
                    install(rid, pfx, ca + m, nh, "O IA")

    # Type 3 LSAs into non-backbone areas
    t3_nb = defaultdict(lambda: defaultdict(list))
    for abr in abrs:
        for pfx, entry in rt[abr].items():
            if entry['type'] not in ("O", "O IA"):
                continue
            src_area = pfx_area.get(pfx)
            for ta in get_areas(abr, routers):
                if ta == 0:
                    continue
                if src_area == ta:
                    continue
                t3_nb[ta][pfx].append((abr, entry['cost']))

    for rid in routers:
        a = routers[rid]['area']
        if a == 0 or routers[rid].get('type') == 'ABR':
            continue
        for pfx, ads in t3_nb.get(a, {}).items():
            for abr, m in ads:
                if a in spf and rid in spf[a] and abr in spf[a][rid]:
                    ca, nh = spf[a][rid][abr]
                    install(rid, pfx, ca + m, nh, "O IA")

    # Phase 4: Stub area default routes
    for astr, acfg in areas_cfg.items():
        a = int(astr)
        if acfg['type'] != 'stub':
            continue
        dc = acfg.get('default_cost', 1)
        for abr in abrs:
            if a not in get_areas(abr, routers):
                continue
            for rid in routers:
                if routers[rid]['area'] != a or rid == abr:
                    continue
                if a in spf and rid in spf[a] and abr in spf[a][rid]:
                    c, nh = spf[a][rid][abr]
                    install(rid, "0.0.0.0/0", c + dc, nh, "O*IA")

    # Phase 5: NSSA default routes
    for astr, acfg in areas_cfg.items():
        a = int(astr)
        if acfg['type'] != 'nssa':
            continue
        dc = acfg.get('default_cost', 1)
        for abr in abrs:
            if a not in get_areas(abr, routers):
                continue
            for rid in routers:
                if routers[rid]['area'] != a or rid == abr:
                    continue
                if a in spf and rid in spf[a] and abr in spf[a][rid]:
                    c, nh = spf[a][rid][abr]
                    install(rid, "0.0.0.0/0", dc, nh, "O*N2", fwd=c)

    # Phase 6: External routes
    for ext in externals:
        asbr = ext['asbr']
        pfx = ext['prefix']
        em = ext['metric']
        et = ext['metric_type']
        asbr_area = routers[asbr]['area']
        atype = areas_cfg[str(asbr_area)]['type']

        if atype == 'nssa':
            # NSSA internal: Type 7 LSAs
            nrt = "O N1" if et == "E1" else "O N2"
            for rid in routers:
                if routers[rid]['area'] != asbr_area or rid == asbr:
                    continue
                if asbr_area in spf and rid in spf[asbr_area]:
                    if asbr in spf[asbr_area][rid]:
                        c, nh = spf[asbr_area][rid][asbr]
                        if et == "E1":
                            install(rid, pfx, em + c, nh, nrt)
                        else:
                            install(rid, pfx, em, nh, nrt, fwd=c)

            # Type 7-to-5 conversion for non-stub/NSSA routers
            ert = "O E1" if et == "E1" else "O E2"
            for rid in routers:
                if rid == asbr:
                    continue
                ra = routers[rid]['area']
                rat = areas_cfg[str(ra)]['type']
                if rat in ('stub', 'nssa'):
                    continue
                ap = routers[asbr]['loopback']
                if ap not in rt[rid]:
                    continue
                c2a = rt[rid][ap]['cost']
                nh = rt[rid][ap]['next_hop']
                if et == "E1":
                    install(rid, pfx, em + c2a, nh, ert)
                else:
                    install(rid, pfx, em, nh, ert, fwd=c2a)
        else:
            # Regular area external routes
            ert = "O E1" if et == "E1" else "O E2"
            for rid in routers:
                if rid == asbr:
                    continue
                ra = routers[rid]['area']
                rat = areas_cfg[str(ra)]['type']
                if rat in ('stub', 'nssa'):
                    continue
                ap = routers[asbr]['loopback']
                if ap not in rt[rid]:
                    continue
                c2a = rt[rid][ap]['cost']
                nh = rt[rid][ap]['next_hop']
                if et == "E1":
                    install(rid, pfx, em + c2a, nh, ert)
                else:
                    install(rid, pfx, em, nh, ert, fwd=c2a)

    return rt


def answer_queries(queries, rt):
    """Look up each query in the computed routing tables."""
    results = []
    for q in queries:
        router, dest = q['router'], q['destination']
        table = rt[router]
        entry = table.get(dest) or table.get("0.0.0.0/0")
        if entry:
            r = {
                "router": router,
                "destination": dest,
                "next_hop": entry['next_hop'],
                "cost": entry['cost'],
                "route_type": entry['type'],
            }
            if 'forward_cost' in entry:
                r['forward_cost'] = entry['forward_cost']
            results.append(r)
        else:
            results.append({
                "router": router,
                "destination": dest,
                "next_hop": None,
                "cost": None,
                "route_type": "unreachable",
            })
    return results


def main():
    # Extract link costs from tshark pcap output
    pcap_costs = extract_pcap_costs('/tmp/pcap_data.json')

    # Load topology from DB, filling NULL costs with pcap data
    topo = load_topology('/app/topology.db', pcap_costs)

    # Load queries from XSLT-transformed XML
    queries = load_queries('/app/queries.xml')

    # Compute OSPF routes
    rt = compute_routes(topo)

    # Answer queries and write results
    results = answer_queries(queries, rt)

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    for r in results:
        fwd = " fwd=%d" % r['forward_cost'] if 'forward_cost' in r else ""
        print("%s -> %s: %s cost=%s via %s%s" % (
            r['router'], r['destination'],
            r['route_type'], r['cost'], r['next_hop'], fwd))


if __name__ == '__main__':
    main()
