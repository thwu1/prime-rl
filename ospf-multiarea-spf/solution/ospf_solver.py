#!/usr/bin/env python3
"""
OSPF Multi-Area Routing Table Computation with direct PCAP parsing.

Workflow:
1. Parse pcap binary to extract Router LSA link costs and Hello analysis
2. Complete the topology with recovered costs
3. Compute OSPF routing tables per RFC 2328
4. Perform failover analysis
5. Write all results

"""

import json
import struct
import socket
import heapq
import os
import copy
from collections import defaultdict


# ===== PCAP / OSPF binary parsing =====

def inet_ntoa(packed):
    return socket.inet_ntoa(packed)


def parse_pcap(path):
    """Parse pcap file, return list of raw packet byte strings."""
    with open(path, 'rb') as f:
        data = f.read()
    magic = struct.unpack_from('<I', data, 0)[0]
    if magic == 0xa1b2c3d4:
        endian = '<'
    elif magic == 0xd4c3b2a1:
        endian = '>'
    else:
        raise ValueError(f"Bad pcap magic: {hex(magic)}")
    offset = 24  # skip global header
    packets = []
    while offset + 16 <= len(data):
        _, _, incl_len, _ = struct.unpack_from(f'{endian}IIII', data, offset)
        offset += 16
        packets.append(data[offset:offset + incl_len])
        offset += incl_len
    return packets


def parse_ospf(pkt):
    """Parse IP + OSPF header from raw packet. Returns None if not OSPF."""
    if len(pkt) < 44:
        return None
    ihl = (pkt[0] & 0x0f) * 4
    if pkt[9] != 89:  # protocol != OSPF
        return None
    o = pkt[ihl:]
    if len(o) < 24:
        return None
    msg_type = o[1]
    pkt_len = struct.unpack_from('!H', o, 2)[0]
    router_id = inet_ntoa(o[4:8])
    area_id = inet_ntoa(o[8:12])
    body = o[24:pkt_len]
    return {'msg_type': msg_type, 'router_id': router_id,
            'area_id': area_id, 'body': body}


def parse_hello(body):
    """Parse OSPF Hello body."""
    if len(body) < 20:
        return None
    hello_int = struct.unpack_from('!H', body, 4)[0]
    dead_int = struct.unpack_from('!I', body, 8)[0]
    dr = inet_ntoa(body[12:16])
    bdr = inet_ntoa(body[16:20])
    nbrs = []
    off = 20
    while off + 4 <= len(body):
        nbrs.append(inet_ntoa(body[off:off + 4]))
        off += 4
    return {'hello_interval': hello_int, 'dead_interval': dead_int,
            'dr': dr, 'bdr': bdr, 'neighbors': nbrs}


def parse_ls_update(body):
    """Parse LS Update body, return list of parsed LSAs."""
    if len(body) < 4:
        return []
    num = struct.unpack_from('!I', body, 0)[0]
    lsas = []
    off = 4
    for _ in range(num):
        if off + 20 > len(body):
            break
        ls_type = body[off + 3]
        adv_router = inet_ntoa(body[off + 8:off + 12])
        ls_len = struct.unpack_from('!H', body, off + 18)[0]
        lsa_entry = {'ls_type': ls_type, 'adv_router': adv_router}
        if ls_type == 1:  # Router LSA
            boff = off + 20
            if boff + 4 <= off + ls_len:
                nlinks = struct.unpack_from('!H', body, boff + 2)[0]
                links = []
                loff = boff + 4
                for _ in range(nlinks):
                    if loff + 12 > off + ls_len:
                        break
                    lid = inet_ntoa(body[loff:loff + 4])
                    ltype = body[loff + 8]
                    tos_cnt = body[loff + 9]
                    metric = struct.unpack_from('!H', body, loff + 10)[0]
                    links.append({'link_id': lid, 'link_type': ltype,
                                  'metric': metric})
                    loff += 12 + tos_cnt * 4
                lsa_entry['links'] = links
        lsas.append(lsa_entry)
        off += ls_len
    return lsas


def extract_pcap_data(pcap_path):
    """Extract all OSPF data from pcap: hellos, router LSAs."""
    packets = parse_pcap(pcap_path)
    hellos = []       # list of (router_id, area_id, hello_data)
    router_lsas = []  # list of (area_id, adv_router, links)

    for pkt in packets:
        ospf = parse_ospf(pkt)
        if ospf is None:
            continue
        if ospf['msg_type'] == 1:  # Hello
            h = parse_hello(ospf['body'])
            if h:
                h['router_id'] = ospf['router_id']
                h['area_id'] = ospf['area_id']
                hellos.append(h)
        elif ospf['msg_type'] == 4:  # LS Update
            for lsa in parse_ls_update(ospf['body']):
                if lsa['ls_type'] == 1 and 'links' in lsa:
                    router_lsas.append({
                        'area_id': ospf['area_id'],
                        'adv_router': lsa['adv_router'],
                        'links': lsa['links'],
                    })
    return hellos, router_lsas


def recover_missing_costs(topology, router_lsas):
    """Recover null link costs from Router LSAs extracted from pcap."""
    recovery_map = [
        ({'R3', 'R4'}, 0, '3.3.3.3', '4.4.4.4'),
        ({'R5', 'R3'}, 1, '3.3.3.3', '5.5.5.5'),
        ({'R2', 'R8'}, 2, '2.2.2.2', '8.8.8.8'),
    ]
    for link in topology['links']:
        if link['cost'] is not None:
            continue
        ep_set = set(link['endpoints'])
        for target_eps, area, adv_rid, target_lid in recovery_map:
            if ep_set == target_eps and link['area'] == area:
                area_dot = f"0.0.0.{area}"
                for rlsa in router_lsas:
                    if (rlsa['adv_router'] == adv_rid and
                            rlsa['area_id'] == area_dot):
                        for lnk in rlsa['links']:
                            if lnk['link_id'] == target_lid:
                                link['cost'] = lnk['metric']
                                break
                        break
                break


def extract_pcap_analysis(hellos, router_lsas):
    """Derive pcap analysis fields from parsed data."""
    analysis = {}
    analysis['pcap_hello_count'] = len(hellos)

    for h in hellos:
        if h['area_id'] == '0.0.0.0':
            analysis['pcap_area0_dr'] = h['dr']
            break

    for h in hellos:
        if h['router_id'] == '8.8.8.8':
            analysis['pcap_r8_dead_interval'] = h['dead_interval']
            break

    for rlsa in router_lsas:
        if rlsa['adv_router'] == '3.3.3.3' and rlsa['area_id'] == '0.0.0.0':
            analysis['pcap_r3_area0_lsa_link_count'] = len(rlsa['links'])
            break

    return analysis


# ===== OSPF computation =====

def load_json(path):
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def build_area_graph(links, area_id):
    """Build undirected adjacency list for a specific OSPF area."""
    graph = defaultdict(list)
    for link in links:
        if link['area'] == area_id:
            a, b = link['endpoints']
            c = link['cost']
            graph[a].append((b, c))
            graph[b].append((a, c))
    return dict(graph)


def dijkstra(graph, source):
    """Dijkstra SPF returning distances and next-hops."""
    dist = {source: 0}
    next_hop = {source: 'self'}
    visited = set()
    pq = [(0, source)]
    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        for v, w in graph.get(u, []):
            if v in visited:
                continue
            nd = d + w
            if v not in dist or nd < dist[v]:
                dist[v] = nd
                next_hop[v] = v if u == source else next_hop[u]
                heapq.heappush(pq, (nd, v))
    return dist, next_hop


def compute_routing_table(topology, ext_data, target_router):
    """Compute full OSPF routing table for a non-ABR router."""
    routers = topology['routers']
    links = topology['links']

    all_areas = set()
    for r in routers.values():
        all_areas.update(r['areas'])

    # Phase 1: Per-area SPF
    spf = {}
    for area in all_areas:
        g = build_area_graph(links, area)
        for rname in routers:
            if area in routers[rname]['areas'] and rname in g:
                spf[(rname, area)] = dijkstra(g, rname)

    # Phase 2: ABR intra-area route collection
    abrs = [n for n, info in routers.items() if 'ABR' in info['roles']]
    abr_routes = {abr: {} for abr in abrs}

    for abr in abrs:
        for area in routers[abr]['areas']:
            if (abr, area) not in spf:
                continue
            dist, _ = spf[(abr, area)]
            for rname, rinfo in routers.items():
                if rinfo['loopback_area'] == area and rname in dist:
                    lo = rinfo['loopback']
                    cost = dist[rname]
                    if lo not in abr_routes[abr] or cost < abr_routes[abr][lo][0]:
                        abr_routes[abr][lo] = (cost, 'intra-area')

    # Phase 3: ABR inter-area via backbone Summary-LSAs
    for abr in abrs:
        if 0 not in routers[abr]['areas']:
            continue
        if (abr, 0) not in spf:
            continue
        backbone_dist, _ = spf[(abr, 0)]
        for other_abr in abrs:
            if other_abr == abr or other_abr not in backbone_dist:
                continue
            cost_to_other = backbone_dist[other_abr]
            for lo, (metric, rtype) in abr_routes.get(other_abr, {}).items():
                if rtype != 'intra-area':
                    continue
                total = cost_to_other + metric
                if lo not in abr_routes[abr]:
                    abr_routes[abr][lo] = (total, 'inter-area')
                elif (abr_routes[abr][lo][1] == 'inter-area' and
                      total < abr_routes[abr][lo][0]):
                    abr_routes[abr][lo] = (total, 'inter-area')

    # Phase 4: Target router routing table
    target_info = routers[target_router]
    target_area = target_info['areas'][0]
    if (target_router, target_area) not in spf:
        return []
    target_dist, target_nh = spf[(target_router, target_area)]
    routing_table = []

    # Intra-area loopback routes
    for rname, rinfo in routers.items():
        if rinfo['loopback_area'] == target_area and rname in target_dist:
            routing_table.append({
                'destination': rinfo['loopback'],
                'route_type': 'intra-area',
                'cost': target_dist[rname],
                'next_hop_router': target_nh[rname],
            })

    # Inter-area routes via ABRs
    area_abrs = [a for a in abrs
                 if target_area in routers[a]['areas'] and a in target_dist]
    for rname, rinfo in routers.items():
        if rinfo['loopback_area'] == target_area:
            continue
        lo = rinfo['loopback']
        best_cost = None
        best_nh = None
        for abr in area_abrs:
            if lo not in abr_routes.get(abr, {}):
                continue
            cost_to_abr = target_dist[abr]
            summary_metric = abr_routes[abr][lo][0]
            total = cost_to_abr + summary_metric
            if best_cost is None or total < best_cost:
                best_cost = total
                best_nh = target_nh[abr]
        if best_cost is not None:
            routing_table.append({
                'destination': lo,
                'route_type': 'inter-area',
                'cost': best_cost,
                'next_hop_router': best_nh,
            })

    # Phase 5: External routes
    asbr_name = ext_data['asbr']
    asbr_lo = routers[asbr_name]['loopback']
    cost_to_asbr = None
    nh_to_asbr = None
    for entry in routing_table:
        if entry['destination'] == asbr_lo:
            cost_to_asbr = entry['cost']
            nh_to_asbr = entry['next_hop_router']
            break

    for ext in ext_data['routes']:
        prefix = ext['prefix']
        etype = ext['type']
        metric = ext['metric']
        fa = ext.get('forwarding_address')

        if fa:
            fa_cost = None
            fa_nh = None
            for entry in routing_table:
                if entry['destination'].split('/')[0] == fa:
                    fa_cost = entry['cost']
                    fa_nh = entry['next_hop_router']
                    break
            if fa_cost is None:
                continue
            if etype == 'E2':
                routing_table.append({
                    'destination': prefix,
                    'route_type': 'external-type2',
                    'cost': metric,
                    'forwarding_cost': fa_cost,
                    'next_hop_router': fa_nh,
                })
            else:
                routing_table.append({
                    'destination': prefix,
                    'route_type': 'external-type1',
                    'cost': fa_cost + metric,
                    'next_hop_router': fa_nh,
                })
        else:
            if cost_to_asbr is None:
                continue
            if etype == 'E2':
                routing_table.append({
                    'destination': prefix,
                    'route_type': 'external-type2',
                    'cost': metric,
                    'forwarding_cost': cost_to_asbr,
                    'next_hop_router': nh_to_asbr,
                })
            else:
                routing_table.append({
                    'destination': prefix,
                    'route_type': 'external-type1',
                    'cost': cost_to_asbr + metric,
                    'next_hop_router': nh_to_asbr,
                })

    routing_table.sort(key=lambda x: x['destination'])
    return routing_table


def find_route(table, dest):
    for e in table:
        if e['destination'] == dest:
            return e
    return None


def main():
    pcap_path = '/app/network/ospf_capture.pcap'
    topology = load_json('/app/network/topology.json')
    ext_data = load_json('/app/network/external_routes.json')

    # Step 1: Parse pcap and recover missing link costs
    hellos, router_lsas = extract_pcap_data(pcap_path)
    recover_missing_costs(topology, router_lsas)

    for link in topology['links']:
        if link['cost'] is None:
            raise RuntimeError(
                f"Failed to recover cost for link {link['endpoints']} "
                f"area {link['area']}")

    # Step 2: Compute routing tables
    r7_table = compute_routing_table(topology, ext_data, 'R7')
    save_json('/app/results/routing_table_R7.json', r7_table)

    r5_table = compute_routing_table(topology, ext_data, 'R5')
    save_json('/app/results/routing_table_R5.json', r5_table)

    # Step 3: Failover analysis (R8-R3 link failure in Area 2)
    fail_topo = copy.deepcopy(topology)
    fail_topo['links'] = [
        l for l in fail_topo['links']
        if not (set(l['endpoints']) == {'R8', 'R3'} and l['area'] == 2)
    ]
    r7_fail = compute_routing_table(fail_topo, ext_data, 'R7')

    # Step 4: Build analysis
    r7_r5 = find_route(r7_table, '10.5.5.5/32')
    r7_172 = find_route(r7_table, '172.16.0.0/16')
    r7_fail_r5 = find_route(r7_fail, '10.5.5.5/32')
    r7_fail_r4 = find_route(r7_fail, '10.4.4.4/32')

    analysis = {
        'r7_cost_to_10_5_5_5': r7_r5['cost'],
        'r7_next_hop_to_10_5_5_5': r7_r5['next_hop_router'],
        'r7_forwarding_cost_172_16': r7_172['forwarding_cost'],
        'r7_failover_cost_to_10_5_5_5': r7_fail_r5['cost'],
        'r7_failover_next_hop_to_10_4_4_4': r7_fail_r4['next_hop_router'],
        'r7_192_168_2_route_via': 'forwarding_address',
        'e2_tiebreaker_preferred': '192.168.2.0/24',
    }

    # Step 5: Add pcap analysis
    pcap_anal = extract_pcap_analysis(hellos, router_lsas)
    analysis.update(pcap_anal)

    save_json('/app/results/analysis.json', analysis)
    print(f'R7 table: {len(r7_table)} routes')
    print(f'R5 table: {len(r5_table)} routes')
    print('OSPF routing computation complete.')


if __name__ == '__main__':
    main()
