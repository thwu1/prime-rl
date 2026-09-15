#!/usr/bin/env python3
"""
OSPF SPF Route Calculator

Implements RFC 2328 Section 16 SPF computation for multi-area OSPF
topologies.  Reads an LSDB encoded as JSON, runs per-area Dijkstra,
and produces a routing table.
"""


import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
import heapq

# ── LSA / link-type constants ────────────────────────────────────────

LINK_P2P = 1
LINK_TRANSIT = 2
LINK_STUB = 3
LINK_VIRTUAL = 4

FLAG_ABR = 0x01
FLAG_ASBR = 0x02

# ── Helpers ──────────────────────────────────────────────────────────

def mask_to_prefix_len(mask_str: str) -> int:
    """Dotted-decimal netmask -> CIDR prefix length."""
    bits = 0
    for octet in mask_str.split('.'):
        bits = (bits << 8) | int(octet)
    return bin(bits).count('1')


def apply_mask(addr: str, mask: str) -> str:
    """Return network address from addr & mask."""
    a = [int(x) for x in addr.split('.')]
    m = [int(x) for x in mask.split('.')]
    return '.'.join(str(a[i] & m[i]) for i in range(4))

# ── Data model ───────────────────────────────────────────────────────

@dataclass
class Link:
    link_id: str
    link_data: str
    link_type: int
    metric: int
    is_loopback: bool = False


@dataclass
class RouterLsa:
    router_id: str
    area_id: str
    flags: int
    links: List[Link]

    @classmethod
    def from_dict(cls, d: dict, area_id: str) -> "RouterLsa":
        links = [
            Link(l["link_id"], l["link_data"], l["link_type"],
                 l["metric"], l.get("is_loopback", False))
            for l in d["links"]
        ]
        return cls(d["router_id"], area_id, d.get("flags", 0), links)


@dataclass
class NetworkLsa:
    ls_id: str
    advertising_router: str
    area_id: str
    network_mask: str
    attached_routers: List[str]

    @classmethod
    def from_dict(cls, d: dict, area_id: str) -> "NetworkLsa":
        return cls(d["ls_id"], d["advertising_router"], area_id,
                   d["network_mask"], d["attached_routers"])


@dataclass
class ExternalLsa:
    ls_id: str
    advertising_router: str
    network_mask: str
    metric_type: int
    metric: int
    forwarding_address: str

    @classmethod
    def from_dict(cls, d: dict) -> "ExternalLsa":
        return cls(d["ls_id"], d["advertising_router"], d["network_mask"],
                   d["metric_type"], d["metric"],
                   d.get("forwarding_address", "0.0.0.0"))

# ── LSDB ─────────────────────────────────────────────────────────────

class Lsdb:
    def __init__(self) -> None:
        self._router: Dict[Tuple[str, str], RouterLsa] = {}
        self._network: Dict[Tuple[str, str], NetworkLsa] = {}
        self.externals: List[ExternalLsa] = []
        self.area_types: Dict[str, str] = {}

    # mutators
    def add_router_lsa(self, lsa: RouterLsa) -> None:
        self._router[(lsa.area_id, lsa.router_id)] = lsa

    def add_network_lsa(self, lsa: NetworkLsa) -> None:
        self._network[(lsa.area_id, lsa.ls_id)] = lsa

    # queries
    def router_lsa(self, area: str, rid: str) -> Optional[RouterLsa]:
        return self._router.get((area, rid))

    def network_lsa(self, area: str, ls_id: str) -> Optional[NetworkLsa]:
        return self._network.get((area, ls_id))

    def router_areas(self, rid: str) -> List[str]:
        return sorted({a for a, r in self._router if r == rid})

    @classmethod
    def from_json(cls, data: dict) -> "Lsdb":
        db = cls()
        for area_id, ad in data.get("areas", {}).items():
            db.area_types[area_id] = ad.get("type", "normal")
            for rd in ad.get("router_lsas", []):
                db.add_router_lsa(RouterLsa.from_dict(rd, area_id))
            for nd in ad.get("network_lsas", []):
                db.add_network_lsa(NetworkLsa.from_dict(nd, area_id))
        for ed in data.get("external_lsas", []):
            db.externals.append(ExternalLsa.from_dict(ed))
        return db

# ── SPF vertex ───────────────────────────────────────────────────────

@dataclass
class SpfVertex:
    vid: str
    vtype: str            # "router" | "network"
    cost: int
    next_hops: Set[str] = field(default_factory=set)
    lsa: Any = None

    def __lt__(self, other: "SpfVertex") -> bool:
        return (self.cost, self.vid) < (other.cost, other.vid)

# ── Route entry ──────────────────────────────────────────────────────

@dataclass
class Route:
    destination: str
    prefix_len: int
    route_type: str
    cost: int
    next_hops: List[str]
    area_id: str = ""

    def to_dict(self) -> dict:
        return {
            "destination": self.destination,
            "prefix_len": self.prefix_len,
            "route_type": self.route_type,
            "cost": self.cost,
            "next_hops": sorted(self.next_hops),
        }

# ── SPF calculator ───────────────────────────────────────────────────

class OspfSpfCalculator:
    """RFC 2328 Section 16 SPF route computation."""

    def __init__(self, lsdb: Lsdb, root_id: str) -> None:
        self.lsdb = lsdb
        self.root_id = root_id
        self.routes: Dict[str, Route] = {}

    # ---- public API ----

    def compute(self) -> Dict[str, Route]:
        trees: Dict[str, Dict[str, SpfVertex]] = {}
        for area in self.lsdb.router_areas(self.root_id):
            tree = self._dijkstra(area)
            trees[area] = tree
            self._install_intra(area, tree)
        self._install_externals(trees)
        return self.routes

    # ---- Dijkstra ----

    def _dijkstra(self, area: str) -> Dict[str, SpfVertex]:
        rlsa = self.lsdb.router_lsa(area, self.root_id)
        if rlsa is None:
            return {}

        root = SpfVertex(self.root_id, "router", 0, set(), rlsa)
        tree: Dict[str, SpfVertex] = {self.root_id: root}
        cands: list = []

        self._expand(area, root, tree, cands)

        while cands:
            best = heapq.heappop(cands)
            if best.vid in tree:
                continue
            tree[best.vid] = best
            self._expand(area, best, tree, cands)

        return tree

    def _expand(self, area: str, v: SpfVertex,
                tree: Dict[str, SpfVertex], cands: list) -> None:
        if v.vtype == "router":
            self._expand_router(area, v, tree, cands)
        else:
            self._expand_network(area, v, tree, cands)

    def _expand_router(self, area: str, v: SpfVertex,
                       tree: Dict[str, SpfVertex], cands: list) -> None:
        """Process outgoing links from a router vertex."""
        rlsa: RouterLsa = v.lsa
        for link in rlsa.links:
            if link.link_type != LINK_TRANSIT:
                continue
            nlsa = self.lsdb.network_lsa(area, link.link_id)
            if nlsa is None or link.link_id in tree:
                continue

            cost = v.cost + link.metric
            if v.vid == self.root_id:
                nh = {link.link_data}       # root's own interface addr
            else:
                nh = set(v.next_hops)
            self._offer(cands, link.link_id, "network", cost, nh, nlsa)

    def _expand_network(self, area: str, v: SpfVertex,
                        tree: Dict[str, SpfVertex], cands: list) -> None:
        """Process attached routers from a network vertex."""
        nlsa: NetworkLsa = v.lsa
        root_on_net = self.root_id in nlsa.attached_routers

        for rid in nlsa.attached_routers:
            if rid in tree:
                continue
            rlsa = self.lsdb.router_lsa(area, rid)
            if rlsa is None:
                continue

            # Locate router's link back to this transit network
            back = None
            for lnk in rlsa.links:
                if lnk.link_type == LINK_TRANSIT and lnk.link_id == v.vid:
                    back = lnk
                    break
            if back is None:
                continue

            # RFC 2328 ss 16.1: when transitioning from a transit network
            # vertex to an attached router, determine the incremental cost
            # using the router's advertised link metric for the connection
            # back to this network.
            cost = v.cost + back.metric

            # next-hop
            if root_on_net:
                nh = {back.link_data}       # router's addr on this net
            else:
                nh = set(v.next_hops)       # inherit

            self._offer(cands, rid, "router", cost, nh, rlsa)

    def _offer(self, cands: list, vid: str, vtype: str,
               cost: int, nh: Set[str], lsa: Any) -> None:
        """Insert or update a candidate vertex."""
        for idx, c in enumerate(cands):
            if c.vid == vid:
                if cost < c.cost:
                    cands[idx] = SpfVertex(vid, vtype, cost, nh, lsa)
                    heapq.heapify(cands)
                elif cost == c.cost:
                    # equal-cost path — update with alternate next-hops
                    c.next_hops = nh
                return
        heapq.heappush(cands, SpfVertex(vid, vtype, cost, nh, lsa))

    # ---- route installation ----

    def _install_intra(self, area: str, tree: Dict[str, SpfVertex]) -> None:
        for v in tree.values():
            if v.vtype == "network":
                nlsa: NetworkLsa = v.lsa
                net = apply_mask(nlsa.ls_id, nlsa.network_mask)
                plen = mask_to_prefix_len(nlsa.network_mask)
                self._add(net, plen, "intra-area", v.cost,
                          list(v.next_hops), area)
            elif v.vtype == "router" and v.lsa is not None:
                self._install_stubs(v, area)

    def _install_stubs(self, v: SpfVertex, area: str) -> None:
        rlsa: RouterLsa = v.lsa
        for link in rlsa.links:
            if link.link_type != LINK_STUB:
                continue

            plen = mask_to_prefix_len(link.link_data)
            net = apply_mask(link.link_id, link.link_data)

            # Unnumbered point-to-point endpoints appear as /32 stub
            # entries on non-loopback interfaces — skip these since they
            # do not represent reachable destination networks.
            if plen == 32 and not link.is_loopback:
                continue

            cost = v.cost + link.metric
            nh = list(v.next_hops) if v.next_hops else ["connected"]
            self._add(net, plen, "intra-area", cost, nh, area)

    def _install_externals(self, trees: Dict[str, Dict[str, SpfVertex]]) -> None:
        for ext in self.lsdb.externals:
            best_cost, best_nh = None, None
            for tree in trees.values():
                if ext.advertising_router in tree:
                    sv = tree[ext.advertising_router]
                    if best_cost is None or sv.cost < best_cost:
                        best_cost = sv.cost
                        best_nh = list(sv.next_hops)
            if best_cost is None:
                continue

            net = apply_mask(ext.ls_id, ext.network_mask)
            plen = mask_to_prefix_len(ext.network_mask)
            if ext.metric_type == 1:
                self._add(net, plen, "external-type1",
                          best_cost + ext.metric, best_nh, "")
            else:
                self._add(net, plen, "external-type2",
                          ext.metric, best_nh, "")

    def _add(self, dest: str, plen: int, rtype: str,
             cost: int, nh: List[str], area: str) -> None:
        key = f"{dest}/{plen}"
        if key not in self.routes or cost < self.routes[key].cost:
            self.routes[key] = Route(dest, plen, rtype, cost, nh, area)

# ── CLI ──────────────────────────────────────────────────────────────

def compute_routes(topo_path: str, router_id: str | None = None) -> dict:
    with open(topo_path) as fh:
        data = json.load(fh)
    rid = router_id or data.get("root_router_id", "1.1.1.1")
    lsdb = Lsdb.from_json(data)
    return {
        k: v.to_dict()
        for k, v in sorted(OspfSpfCalculator(lsdb, rid).compute().items())
    }


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <topology.json> [router_id]",
              file=sys.stderr)
        sys.exit(1)
    rid = sys.argv[2] if len(sys.argv) > 2 else None
    print(json.dumps(compute_routes(sys.argv[1], rid), indent=2))


if __name__ == "__main__":
    main()
