#!/usr/bin/env python3
"""
Distance Vector Routing Daemon
Processes network topology and produces routing tables.
"""
import json
import sys

INF = 9999


class DVSimulator:
    def __init__(self, nodes, links):
        self.all_nodes = sorted(nodes)
        self.active_nodes = set(nodes)
        self.adj = {n: {} for n in self.all_nodes}
        for link in links:
            s, d, c = link["src"], link["dst"], link["cost"]
            if c < INF:
                self.adj[s][d] = c
                self.adj[d][s] = c
        self.dv = {}
        self.nexthop = {}
        self._init_tables()

    def _init_tables(self):
        """Initialize distance vectors with direct link costs."""
        for n in self.all_nodes:
            self.dv[n] = {}
            self.nexthop[n] = {}
            for d in self.all_nodes:
                if d == n and n in self.active_nodes:
                    self.dv[n][d] = 0
                    self.nexthop[n][d] = n
                elif (n in self.active_nodes and d in self.active_nodes
                      and d in self.adj.get(n, {})):
                    self.dv[n][d] = self.adj[n][d]
                    self.nexthop[n][d] = d
                else:
                    self.dv[n][d] = INF
                    self.nexthop[n][d] = None

    def _get_advertised_dv(self, sender, receiver):
        """Build the distance vector that sender advertises to receiver."""
        adv = {}
        for dest in self.all_nodes:
            adv[dest] = self.dv[sender].get(dest, INF)
        return adv

    def converge(self):
        """Run iterative DV computation until convergence. Returns round count."""
        rounds = 0
        while True:
            rounds += 1
            changed = False
            new_dv = {n: dict(self.dv[n]) for n in self.all_nodes}
            new_nexthop = {n: dict(self.nexthop[n]) for n in self.all_nodes}

            for n in self.all_nodes:
                if n not in self.active_nodes:
                    continue
                for dest in self.all_nodes:
                    if dest == n:
                        continue
                    best_cost = INF
                    best_hop = None
                    for neighbor in sorted(self.adj.get(n, {})):
                        if neighbor not in self.active_nodes:
                            continue
                        link_cost = self.adj[n][neighbor]
                        adv_dv = self._get_advertised_dv(neighbor, n)
                        route_cost = link_cost + adv_dv.get(dest, INF)
                        if route_cost >= INF:
                            route_cost = INF
                        if route_cost < best_cost or (
                            route_cost == best_cost
                            and best_hop is not None
                            and neighbor > best_hop
                        ):
                            best_cost = route_cost
                            best_hop = neighbor
                    if best_cost != self.dv[n][dest]:
                        changed = True
                    new_dv[n][dest] = best_cost
                    new_nexthop[n][dest] = best_hop

            self.dv = new_dv
            self.nexthop = new_nexthop
            if not changed or rounds >= 200:
                break
        return rounds

    def get_tables(self):
        """Return current routing tables."""
        tables = {}
        for n in self.all_nodes:
            tables[n] = {}
            for d in self.all_nodes:
                if n not in self.active_nodes:
                    tables[n][d] = [INF, None]
                else:
                    cost = self.dv[n][d]
                    nh = self.nexthop[n][d]
                    if cost >= INF:
                        tables[n][d] = [INF, None]
                    else:
                        tables[n][d] = [cost, nh]
        return tables

    def apply_event(self, event):
        """Apply a topology event."""
        etype = event["type"]

        if etype == "update":
            s, d, c = event["src"], event["dst"], event["cost"]
            if c >= INF:
                # Remove link
                self.adj.get(s, {}).pop(d, None)
                self.adj.get(d, {}).pop(s, None)
            else:
                # Add or update link cost
                if s not in self.adj:
                    self.adj[s] = {}
                if d not in self.adj:
                    self.adj[d] = {}
                self.adj[s][d] = c
                self.adj[d][s] = c
                if s in self.active_nodes and d in self.active_nodes:
                    if c < self.dv[s].get(d, INF):
                        self.dv[s][d] = c
                        self.nexthop[s][d] = d
                    if c < self.dv[d].get(s, INF):
                        self.dv[d][s] = c
                        self.nexthop[d][s] = s
                    for n in [s, d]:
                        other = d if n == s else s
                        if self.nexthop[n].get(other) == other:
                            self.dv[n][other] = c

        elif etype == "crash":
            node = event["node"]
            self.active_nodes.discard(node)
            # Mark crashed node as fully unreachable
            for d in self.all_nodes:
                self.dv[node][d] = INF
                self.nexthop[node][d] = None
            # Remove all links to/from crashed node
            neighbors = list(self.adj.get(node, {}).keys())
            for nb in neighbors:
                self.adj.get(nb, {}).pop(node, None)
            self.adj[node] = {}
            # Notify active nodes that crashed node is unreachable
            for n in self.active_nodes:
                self.dv[n][node] = INF
                self.nexthop[n][node] = None

        elif etype == "revive":
            node = event["node"]
            self.active_nodes.add(node)
            self.adj[node] = {}
            for d in self.all_nodes:
                self.dv[node][d] = INF
                self.nexthop[node][d] = None
            self.dv[node][node] = 0
            self.nexthop[node][node] = node


def main():
    with open("/app/topology.json") as f:
        topo = json.load(f)

    sim = DVSimulator(topo["nodes"], topo["initial_links"])
    convergence_log = []

    # Phase 0: initial convergence
    rounds = sim.converge()
    convergence_log.append({
        "phase": 0,
        "rounds": rounds,
        "tables": sim.get_tables()
    })

    # Process topology events
    for i, event in enumerate(topo["events"]):
        sim.apply_event(event)
        rounds = sim.converge()
        convergence_log.append({
            "phase": i + 1,
            "rounds": rounds,
            "tables": sim.get_tables()
        })

    # Write outputs
    with open("/app/routing_tables.json", "w") as f:
        json.dump(sim.get_tables(), f, indent=2)

    with open("/app/convergence_log.json", "w") as f:
        json.dump(convergence_log, f, indent=2)


if __name__ == "__main__":
    main()
