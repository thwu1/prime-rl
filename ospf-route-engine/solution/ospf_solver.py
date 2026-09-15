#!/usr/bin/env python3
"""
OSPF SPF Route Calculator
Computes the IP routing table from an OSPF Link State Database per RFC 2328.

"""
import json
import heapq
from ipaddress import IPv4Network


def mask_to_prefixlen(mask):
    """Convert dotted-decimal subnet mask to prefix length."""
    return sum(bin(int(o)).count('1') for o in mask.split('.'))


def run_spf(computing_router, router_lsas):
    """
    Run Dijkstra's SPF on Area 0 Router LSAs (point-to-point links only).
    Returns (spf_tree, lsa_map).
    spf_tree: dict router_id -> (cost, set_of_next_hop_ips)
    """
    lsa_map = {lsa['adv_router']: lsa for lsa in router_lsas}

    def neighbor_ip(neighbor_id, our_id):
        nlsa = lsa_map.get(neighbor_id)
        if not nlsa:
            return None
        for link in nlsa['links']:
            if link['type'] == 'point-to-point' and link['link_id'] == our_id:
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
            if link['type'] != 'point-to-point':
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
    """Extract stub-network routes from each SPF vertex."""
    routes = {}
    for rid, (rcost, rnhs) in spf_tree.items():
        lsa = lsa_map.get(rid)
        if not lsa:
            continue
        for link in lsa['links']:
            if link['type'] != 'stub':
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
    """Compute inter-area routes from Type 3 Summary LSAs."""
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
    """Compute cost to each ASBR via Type 4 ASBR-Summary LSAs."""
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
    """Compute Type 5 external routes. E1 preferred over E2 per RFC 2328 s16.4."""
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
    with open('/app/lsdb.json') as f:
        lsdb = json.load(f)

    cr = lsdb['computing_router']
    spf_tree, lsa_map = run_spf(cr, lsdb['router_lsas'])
    intra = compute_intra_routes(cr, spf_tree, lsa_map)
    inter = compute_inter_routes(cr, lsdb['summary_lsas'], spf_tree, intra)
    asbr = compute_asbr_costs(lsdb['asbr_summary_lsas'], spf_tree, cr)
    ext = compute_external_routes(lsdb['external_lsas'], asbr, intra, inter)

    table = []
    for routes in [intra, inter, ext]:
        for prefix, (cost, rtype, nhs) in routes.items():
            table.append({
                "destination": prefix,
                "cost": cost,
                "route_type": rtype,
                "next_hops": sorted(nhs)
            })

    table.sort(key=lambda r: (
        IPv4Network(r['destination']).network_address,
        IPv4Network(r['destination']).prefixlen
    ))

    with open('/app/routing_table.json', 'w') as f:
        json.dump(table, f, indent=2)
    print(f"Computed {len(table)} routes")


if __name__ == '__main__':
    main()
