#!/usr/bin/env python3
"""
Parse OSPF pcap and compute the complete routing table per RFC 2328.

"""
import json
import heapq
from ipaddress import IPv4Network

from scapy.all import rdpcap, conf
conf.verb = 0
from scapy.contrib.ospf import (
    OSPF_LSUpd, OSPF_Router_LSA, OSPF_Link,
    OSPF_SummaryIP_LSA, OSPF_External_LSA,
)


def mask_to_prefixlen(mask):
    return sum(bin(int(o)).count('1') for o in mask.split('.'))


def extract_lsdb(pcap_path):
    """Read pcap and extract all OSPF LSAs, deduplicating by highest seq."""
    packets = rdpcap(pcap_path)
    router_lsas = {}
    summary_lsas = {}
    asbr_summary_lsas = {}
    external_lsas = {}

    for pkt in packets:
        if not pkt.haslayer(OSPF_LSUpd):
            continue
        upd = pkt.getlayer(OSPF_LSUpd)
        for lsa in upd.lsalist:
            t = getattr(lsa, 'type', 0)
            lid = getattr(lsa, 'id', None)
            adv = getattr(lsa, 'adrouter', None)
            seq = getattr(lsa, 'seq', 0)
            if lid is None or adv is None:
                continue
            key = (lid, adv)

            if t == 1:
                if key not in router_lsas or seq > router_lsas[key]['seq']:
                    links = []
                    for link in getattr(lsa, 'linklist', []):
                        links.append({
                            'type': link.type,
                            'link_id': link.id,
                            'link_data': link.data,
                            'metric': link.metric,
                        })
                    router_lsas[key] = {
                        'adv_router': adv, 'links': links, 'seq': seq,
                    }
            elif t == 3:
                if key not in summary_lsas or seq > summary_lsas[key]['seq']:
                    summary_lsas[key] = {
                        'ls_id': lid, 'adv_router': adv, 'seq': seq,
                        'mask': lsa.mask, 'metric': lsa.metric,
                    }
            elif t == 4:
                if key not in asbr_summary_lsas or seq > asbr_summary_lsas[key]['seq']:
                    asbr_summary_lsas[key] = {
                        'ls_id': lid, 'adv_router': adv, 'seq': seq,
                        'metric': lsa.metric,
                    }
            elif t == 5:
                if key not in external_lsas or seq > external_lsas[key]['seq']:
                    ebit = getattr(lsa, 'ebit', 0)
                    external_lsas[key] = {
                        'ls_id': lid, 'adv_router': adv, 'seq': seq,
                        'mask': lsa.mask, 'metric': lsa.metric,
                        'metric_type': 'E2' if ebit else 'E1',
                    }

    return (list(router_lsas.values()), list(summary_lsas.values()),
            list(asbr_summary_lsas.values()), list(external_lsas.values()))


def run_spf(computing_router, router_lsas):
    """Dijkstra SPF on Router LSAs (point-to-point links)."""
    lsa_map = {lsa['adv_router']: lsa for lsa in router_lsas}

    def neighbor_ip(neighbor_id, our_id):
        nlsa = lsa_map.get(neighbor_id)
        if not nlsa:
            return None
        for link in nlsa['links']:
            if link['type'] == 1 and link['link_id'] == our_id:
                return link['link_data']
        return None

    dist = {computing_router: (0, set())}
    visited = set()
    heap = [(0, computing_router)]

    while heap:
        cost, u = heapq.heappop(heap)
        if u in visited:
            continue
        visited.add(u)

        lsa = lsa_map.get(u)
        if not lsa:
            continue

        for link in lsa['links']:
            if link['type'] != 1:
                continue
            v = link['link_id']
            if v in visited:
                continue
            new_cost = cost + link['metric']

            if u == computing_router:
                nip = neighbor_ip(v, u)
                if nip is None:
                    continue
                nhs = {nip}
            else:
                nhs = set(dist[u][1])

            if v not in dist or new_cost < dist[v][0]:
                dist[v] = (new_cost, nhs)
                heapq.heappush(heap, (new_cost, v))
            elif new_cost == dist[v][0]:
                dist[v][1].update(nhs)

    return dist, lsa_map


def compute_intra_routes(computing_router, spf_tree, lsa_map):
    routes = {}
    for rid, (rcost, rnhs) in spf_tree.items():
        lsa = lsa_map.get(rid)
        if not lsa:
            continue
        for link in lsa['links']:
            if link['type'] != 3:
                continue
            plen = mask_to_prefixlen(link['link_data'])
            prefix = str(IPv4Network(f"{link['link_id']}/{plen}", strict=False))
            total = rcost + link['metric']
            nh = {"connected"} if rid == computing_router else set(rnhs)
            if prefix not in routes or total < routes[prefix][0]:
                routes[prefix] = [total, "intra-area", set(nh)]
            elif total == routes[prefix][0]:
                routes[prefix][2].update(nh)
    return routes


def compute_inter_routes(computing_router, summary_lsas, spf_tree, intra_routes):
    routes = {}
    for lsa in summary_lsas:
        abr = lsa['adv_router']
        if abr == computing_router or abr not in spf_tree:
            continue
        abr_cost, abr_nhs = spf_tree[abr]
        plen = mask_to_prefixlen(lsa['mask'])
        prefix = str(IPv4Network(f"{lsa['ls_id']}/{plen}", strict=False))
        if prefix in intra_routes:
            continue
        total = abr_cost + lsa['metric']
        if prefix not in routes or total < routes[prefix][0]:
            routes[prefix] = [total, "inter-area", set(abr_nhs)]
        elif total == routes[prefix][0]:
            routes[prefix][2].update(abr_nhs)
    return routes


def compute_asbr_costs(asbr_summary_lsas, spf_tree, computing_router):
    costs = {}
    for lsa in asbr_summary_lsas:
        abr = lsa['adv_router']
        asbr = lsa['ls_id']
        if abr == computing_router or abr not in spf_tree:
            continue
        abr_cost, abr_nhs = spf_tree[abr]
        total = abr_cost + lsa['metric']
        if asbr not in costs or total < costs[asbr][0]:
            costs[asbr] = [total, set(abr_nhs)]
        elif total == costs[asbr][0]:
            costs[asbr][1].update(abr_nhs)
    return costs


def compute_external_routes(external_lsas, asbr_costs, intra_routes, inter_routes):
    e1 = {}
    e2 = {}
    for lsa in external_lsas:
        asbr = lsa['adv_router']
        if asbr not in asbr_costs:
            continue
        asbr_cost, asbr_nhs = asbr_costs[asbr]
        plen = mask_to_prefixlen(lsa['mask'])
        prefix = str(IPv4Network(f"{lsa['ls_id']}/{plen}", strict=False))
        if prefix in intra_routes or prefix in inter_routes:
            continue

        if lsa['metric_type'] == 'E1':
            total = asbr_cost + lsa['metric']
            if prefix not in e1 or total < e1[prefix][0]:
                e1[prefix] = [total, set(asbr_nhs)]
            elif total == e1[prefix][0]:
                e1[prefix][1].update(asbr_nhs)
        elif lsa['metric_type'] == 'E2':
            ext = lsa['metric']
            if prefix not in e2:
                e2[prefix] = [ext, asbr_cost, set(asbr_nhs)]
            elif ext < e2[prefix][0]:
                e2[prefix] = [ext, asbr_cost, set(asbr_nhs)]
            elif ext == e2[prefix][0]:
                if asbr_cost < e2[prefix][1]:
                    e2[prefix] = [ext, asbr_cost, set(asbr_nhs)]
                elif asbr_cost == e2[prefix][1]:
                    e2[prefix][2].update(asbr_nhs)

    result = {}
    for prefix in set(e1) | set(e2):
        if prefix in e1:
            cost, nhs = e1[prefix]
            result[prefix] = [cost, "type-1-external", nhs]
        else:
            cost, _, nhs = e2[prefix]
            result[prefix] = [cost, "type-2-external", nhs]
    return result


def main():
    computing_router = "1.1.1.1"
    router_lsas, summary_lsas, asbr_summary_lsas, external_lsas = \
        extract_lsdb('/app/ospf_capture.pcap')

    print(f"Extracted: {len(router_lsas)} Router, {len(summary_lsas)} Summary, "
          f"{len(asbr_summary_lsas)} ASBR-Summary, {len(external_lsas)} External LSAs")

    spf_tree, lsa_map = run_spf(computing_router, router_lsas)
    intra = compute_intra_routes(computing_router, spf_tree, lsa_map)
    inter = compute_inter_routes(computing_router, summary_lsas, spf_tree, intra)
    asbr = compute_asbr_costs(asbr_summary_lsas, spf_tree, computing_router)
    ext = compute_external_routes(external_lsas, asbr, intra, inter)

    table = []
    for routes in [intra, inter, ext]:
        for prefix, (cost, rtype, nhs) in routes.items():
            table.append({
                "destination": prefix,
                "cost": cost,
                "route_type": rtype,
                "next_hops": sorted(nhs),
            })

    table.sort(key=lambda r: (
        IPv4Network(r['destination']).network_address,
        IPv4Network(r['destination']).prefixlen,
    ))

    with open('/app/routing_table.json', 'w') as f:
        json.dump(table, f, indent=2)
    print(f"Computed {len(table)} routes -> /app/routing_table.json")


if __name__ == '__main__':
    main()
