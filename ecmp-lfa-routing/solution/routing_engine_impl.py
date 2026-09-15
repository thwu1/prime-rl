"""
Routing analysis engine - Solution

"""

import heapq
from collections import defaultdict


class RoutingEngine:

    def __init__(self):
        self._adj = defaultdict(dict)
        self._nodes = set()

    def update_link(self, src, dst, cost):
        assert cost > 0
        self._nodes.add(src)
        self._nodes.add(dst)
        self._adj[src][dst] = cost

    def remove_link(self, src, dst):
        if src in self._adj and dst in self._adj[src]:
            del self._adj[src][dst]

    def get_nodes(self):
        return frozenset(self._nodes)

    def get_neighbors(self, node):
        return dict(self._adj.get(node, {}))

    def _dijkstra(self, source):
        settled = {}
        tent_dist = {source: 0}
        tent_nh = {}
        counter = 0
        pq = [(0, counter, source)]

        while pq:
            d, _, u = heapq.heappop(pq)
            if u in settled:
                continue
            settled[u] = d

            for v, w in self._adj.get(u, {}).items():
                if v in settled:
                    continue
                nd = d + w
                curr = tent_dist.get(v, float('inf'))
                if nd < curr:
                    tent_dist[v] = nd
                    if u == source:
                        tent_nh[v] = {v}
                    else:
                        tent_nh[v] = set(tent_nh.get(u, set()))
                    counter += 1
                    heapq.heappush(pq, (nd, counter, v))
                elif nd == curr:
                    if v not in tent_nh:
                        tent_nh[v] = set()
                    if u == source:
                        tent_nh[v].add(v)
                    else:
                        tent_nh[v].update(tent_nh.get(u, set()))

        nexthops = {}
        for k in settled:
            if k != source and k in tent_nh:
                nexthops[k] = frozenset(tent_nh[k])

        return settled, nexthops

    def shortest_path_distances(self, source):
        settled, _ = self._dijkstra(source)
        return {k: v for k, v in settled.items() if k != source}

    def ecmp_next_hops(self, source):
        _, nexthops = self._dijkstra(source)
        return nexthops

    def compute_backup_nexthops(self, source):
        s_dist, s_nh = self._dijkstra(source)
        neighbors = self._adj.get(source, {})

        n_dists = {}
        for n in neighbors:
            n_dist, _ = self._dijkstra(n)
            n_dists[n] = n_dist

        result = {}
        for dest in s_nh:
            primary = s_nh[dest]
            dist_s_d = s_dist[dest]
            link_prot = set()
            node_prot = set()

            for n in neighbors:
                if n in primary:
                    continue

                dist_n_d = n_dists[n].get(dest)
                dist_n_s = n_dists[n].get(source)
                if dist_n_d is None or dist_n_s is None:
                    continue

                if dist_n_d < dist_n_s + dist_s_d:
                    link_prot.add(n)

                    is_np = True
                    for e in primary:
                        dist_n_e = n_dists[n].get(e)
                        dist_e_d = n_dists.get(e, {}).get(dest)
                        if dist_n_e is None or dist_e_d is None:
                            is_np = False
                            break
                        if not (dist_n_d < dist_n_e + dist_e_d):
                            is_np = False
                            break
                    if is_np:
                        node_prot.add(n)

            result[dest] = {
                'link_protecting': frozenset(link_prot),
                'node_protecting': frozenset(node_prot),
            }

        return result

    def backup_coverage(self, source):
        bak = self.compute_backup_nexthops(source)
        total = len(bak)
        if total == 0:
            return {
                'link_protecting_pct': 100.0,
                'node_protecting_pct': 100.0,
                'unprotected': frozenset(),
            }

        lp = sum(1 for v in bak.values() if v['link_protecting'])
        np_count = sum(1 for v in bak.values() if v['node_protecting'])
        unprot = frozenset(d for d, v in bak.items() if not v['link_protecting'])

        return {
            'link_protecting_pct': 100.0 * lp / total,
            'node_protecting_pct': 100.0 * np_count / total,
            'unprotected': unprot,
        }

    def forwarding_table(self, source):
        s_dist, s_nh = self._dijkstra(source)
        bak = self.compute_backup_nexthops(source)

        table = {}
        for dest in s_nh:
            bak_entry = bak.get(dest, {})
            table[dest] = {
                'cost': s_dist[dest],
                'primary': s_nh[dest],
                'link_backup': bak_entry.get('link_protecting', frozenset()),
                'node_backup': bak_entry.get('node_protecting', frozenset()),
            }
        return table

    def process_events(self, events, query_source):
        tables = []
        for event in events:
            etype = event[0]
            if etype == 'add':
                self.update_link(event[1], event[2], event[3])
            elif etype == 'remove':
                self.remove_link(event[1], event[2])
            elif etype == 'add_symmetric':
                self.update_link(event[1], event[2], event[3])
                self.update_link(event[2], event[1], event[3])
            elif etype == 'add_asymmetric':
                self.update_link(event[1], event[2], event[3])
                self.update_link(event[2], event[1], event[4])
            elif etype == 'remove_symmetric':
                self.remove_link(event[1], event[2])
                self.remove_link(event[2], event[1])
            tables.append(self.forwarding_table(query_source))
        return tables
