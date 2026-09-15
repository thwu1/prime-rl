#!/usr/bin/env python3
"""Generate reference routing data from a correct implementation."""
import json
import os

INF = 9999


class _RefDVSim:
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
        self._init()

    def _init(self):
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

    def _adv(self, sender, receiver):
        adv = {}
        for dest in self.all_nodes:
            if self.nexthop[sender].get(dest) == receiver and dest != sender:
                adv[dest] = INF
            else:
                adv[dest] = self.dv[sender].get(dest, INF)
        return adv

    def converge(self):
        rounds = 0
        while True:
            rounds += 1
            changed = False
            nd = {n: dict(self.dv[n]) for n in self.all_nodes}
            nn = {n: dict(self.nexthop[n]) for n in self.all_nodes}
            for n in self.all_nodes:
                if n not in self.active_nodes:
                    continue
                for dest in self.all_nodes:
                    if dest == n:
                        continue
                    bc = INF
                    bh = None
                    for nb in sorted(self.adj.get(n, {})):
                        if nb not in self.active_nodes:
                            continue
                        lc = self.adj[n][nb]
                        av = self._adv(nb, n)
                        rc = lc + av.get(dest, INF)
                        if rc >= INF:
                            rc = INF
                        if rc < bc or (rc == bc and bh is not None and nb < bh):
                            bc = rc
                            bh = nb
                    if bc != self.dv[n][dest]:
                        changed = True
                    nd[n][dest] = bc
                    nn[n][dest] = bh
            self.dv = nd
            self.nexthop = nn
            if not changed or rounds >= 200:
                break
        return rounds

    def tables(self):
        t = {}
        for n in self.all_nodes:
            t[n] = {}
            for d in self.all_nodes:
                if n not in self.active_nodes:
                    t[n][d] = [INF, None]
                else:
                    c = self.dv[n][d]
                    h = self.nexthop[n][d]
                    if c >= INF:
                        t[n][d] = [INF, None]
                    else:
                        t[n][d] = [c, h]
        return t

    def event(self, ev):
        et = ev["type"]
        if et == "update":
            s, d, c = ev["src"], ev["dst"], ev["cost"]
            if c >= INF:
                self.adj.get(s, {}).pop(d, None)
                self.adj.get(d, {}).pop(s, None)
                for n in [s, d]:
                    if n in self.active_nodes:
                        o = d if n == s else s
                        for dst in self.all_nodes:
                            if self.nexthop[n].get(dst) == o:
                                self.dv[n][dst] = INF
                                self.nexthop[n][dst] = None
            else:
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
                        o = d if n == s else s
                        if self.nexthop[n].get(o) == o:
                            self.dv[n][o] = c
        elif et == "crash":
            node = ev["node"]
            self.active_nodes.discard(node)
            for d in self.all_nodes:
                self.dv[node][d] = INF
                self.nexthop[node][d] = None
            nbs = list(self.adj.get(node, {}).keys())
            for nb in nbs:
                self.adj.get(nb, {}).pop(node, None)
            self.adj[node] = {}
            for n in self.active_nodes:
                self.dv[n][node] = INF
                self.nexthop[n][node] = None
            for n in self.active_nodes:
                for d in self.all_nodes:
                    if self.nexthop[n].get(d) == node:
                        self.dv[n][d] = INF
                        self.nexthop[n][d] = None
        elif et == "revive":
            node = ev["node"]
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

    os.makedirs("/app/reference", exist_ok=True)
    sim = _RefDVSim(topo["nodes"], topo["initial_links"])

    rounds = sim.converge()
    phase0 = sim.tables()
    rc = [rounds]

    with open("/app/reference/phase0_tables.json", "w") as f:
        json.dump(phase0, f, indent=2)

    for ev in topo["events"]:
        sim.event(ev)
        rounds = sim.converge()
        rc.append(rounds)

    with open("/app/reference/final_tables.json", "w") as f:
        json.dump(sim.tables(), f, indent=2)

    with open("/app/reference/round_counts.json", "w") as f:
        json.dump(rc, f, indent=2)

    with open("/app/reference/README.txt", "w") as f:
        f.write("Reference routing data from a verified deployment.\n\n")
        f.write("phase0_tables.json  — Correct routing tables after initial convergence\n")
        f.write("final_tables.json   — Correct final routing tables after all events\n")
        f.write("round_counts.json   — Expected convergence round counts per phase\n")


if __name__ == "__main__":
    main()
