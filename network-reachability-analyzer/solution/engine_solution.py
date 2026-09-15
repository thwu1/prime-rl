#!/usr/bin/env python3
"""Network Reachability Analysis Engine — reference solution.

Loads an enterprise network topology (routers, hosts, static routes, ACLs,
NAT rules) and determines hop-by-hop reachability for every ordered pair of
hosts.  Also detects misconfigurations (black-hole routes, ACL rule shadowing).

Output: /app/report.json
"""


import json
import sys


# ── IP / CIDR arithmetic ───────────────────────────────────────────

def ip_to_int(ip):
    """Dotted-decimal string -> 32-bit unsigned integer."""
    a, b, c, d = (int(o) for o in ip.split("."))
    return (a << 24) | (b << 16) | (c << 8) | d


def int_to_ip(n):
    """32-bit unsigned integer -> dotted-decimal string."""
    return f"{(n >> 24) & 0xFF}.{(n >> 16) & 0xFF}.{(n >> 8) & 0xFF}.{n & 0xFF}"


def prefix_to_mask(pfx):
    """Prefix length (0-32) -> 32-bit mask integer."""
    if pfx == 0:
        return 0
    return ((1 << 32) - 1) << (32 - pfx) & 0xFFFFFFFF


def network_addr(ip, pfx):
    """Return the network address for *ip* with prefix length *pfx*."""
    return int_to_ip(ip_to_int(ip) & prefix_to_mask(pfx))


def ip_in_network(ip, net, pfx):
    """True if *ip* falls inside *net*/*pfx*."""
    mask = prefix_to_mask(pfx)
    return (ip_to_int(ip) & mask) == (ip_to_int(net) & mask)


def parse_cidr(cidr):
    """'x.x.x.x/n' -> (network_str, prefix_len_int)"""
    net, pfx = cidr.split("/")
    return net, int(pfx)


# ── Engine ──────────────────────────────────────────────────────────

class ReachabilityEngine:
    def __init__(self, topo_path):
        with open(topo_path) as fh:
            self.topo = json.load(fh)
        self.routers = self.topo["routers"]
        self.hosts = self.topo["hosts"]
        self.fibs = {}          # router_name -> [route_dict, ...]

    # ── forwarding tables ───────────────────────────────────────────

    def build_fibs(self):
        """Derive each router's FIB from connected interfaces + static routes."""
        for rname, rdata in self.routers.items():
            fib = []
            # Connected routes (implicit from interface addresses)
            for iname, idata in rdata["interfaces"].items():
                net = network_addr(idata["ip"], idata["prefix"])
                fib.append({
                    "network": net,
                    "prefix": idata["prefix"],
                    "next_hop": None,
                    "iface": iname,
                    "rtype": "connected",
                })
            # Static routes
            for sr in rdata.get("static_routes", []):
                fib.append({
                    "network": sr["network"],
                    "prefix": sr["prefix"],
                    "next_hop": sr["next_hop"],
                    "iface": None,
                    "rtype": "static",
                })
            self.fibs[rname] = fib

    def lpm(self, router, dst_ip):
        """Longest-prefix-match lookup. Returns best route dict or None."""
        best, best_pfx = None, -1
        for route in self.fibs[router]:
            if ip_in_network(dst_ip, route["network"], route["prefix"]):
                if route["prefix"] > best_pfx:
                    best_pfx = route["prefix"]
                    best = route
        return best

    def resolve_nexthop(self, router, nh_ip):
        """Return the interface on *router* whose connected network contains *nh_ip*,
        or None if the next-hop is unreachable."""
        for route in self.fibs[router]:
            if route["rtype"] == "connected":
                if ip_in_network(nh_ip, route["network"], route["prefix"]):
                    return route["iface"]
        return None

    # ── helpers ─────────────────────────────────────────────────────

    def _gateway_router(self, host_ip):
        """Return (router_name, entry_iface) for a host's default gateway."""
        for hdata in self.hosts.values():
            if hdata["ip"] == host_ip:
                gw = hdata["gateway"]
                for rname, rdata in self.routers.items():
                    for iname, idata in rdata["interfaces"].items():
                        if idata["ip"] == gw:
                            return rname, iname
        return None, None

    def _router_by_ip(self, ip):
        """Return (router_name, iface_name) owning *ip*, or (None, None)."""
        for rname, rdata in self.routers.items():
            for iname, idata in rdata["interfaces"].items():
                if idata["ip"] == ip:
                    return rname, iname
        return None, None

    def _same_subnet(self, ip1, ip2):
        """True when two host IPs share the same L2 segment (same gateway + network)."""
        h1 = h2 = None
        for hdata in self.hosts.values():
            if hdata["ip"] == ip1:
                h1 = hdata
            if hdata["ip"] == ip2:
                h2 = hdata
        if not h1 or not h2:
            return False
        if h1["gateway"] != h2["gateway"]:
            return False
        return (network_addr(ip1, h1["prefix"]) == network_addr(ip2, h2["prefix"])
                and h1["prefix"] == h2["prefix"])

    # ── ACL evaluation ─────────────────────────────────────────────

    def eval_acl(self, rules, src_ip, dst_ip, proto="any", dport=None):
        """Evaluate ACL rules in ascending ID order (first match wins).
        Returns 'permit' or 'deny'.  Implicit permit if nothing matches."""
        for rule in sorted(rules, key=lambda r: r["id"]):
            # Source check
            r_src, r_src_p = parse_cidr(rule["src"])
            if not ip_in_network(src_ip, r_src, r_src_p):
                continue
            # Destination check
            r_dst, r_dst_p = parse_cidr(rule["dst"])
            if not ip_in_network(dst_ip, r_dst, r_dst_p):
                continue
            # Protocol check
            r_proto = rule.get("protocol", "any")
            if r_proto != "any" and proto != "any" and r_proto != proto:
                continue
            # Destination port check
            if "dst_port" in rule:
                if dport is None or rule["dst_port"] != dport:
                    continue
            return rule["action"]
        return "permit"

    # ── NAT ────────────────────────────────────────────────────────

    def apply_snat(self, router, iface, direction, src_ip, dst_ip):
        """Apply source NAT (masquerade) if a matching rule exists.
        Returns (possibly-translated src_ip, dst_ip)."""
        nat_rules = self.routers[router].get("nat", {})
        key = f"{iface}_{direction}"
        if key not in nat_rules:
            return src_ip, dst_ip
        nr = nat_rules[key]
        if nr["type"] == "masquerade" and direction == "out":
            match_net, match_pfx = parse_cidr(nr["src_match"])
            if ip_in_network(src_ip, match_net, match_pfx):
                return nr["translate_to"], dst_ip
        return src_ip, dst_ip

    # ── packet trace ───────────────────────────────────────────────

    def trace(self, src_ip, dst_ip, max_hops=20):
        """Trace a packet from *src_ip* to *dst_ip*.
        Returns (reachable: bool, path: list, reason: str)."""

        # Direct delivery on the same L2 segment
        if self._same_subnet(src_ip, dst_ip):
            return True, [src_ip, dst_ip], "direct_delivery"

        router, entry_iface = self._gateway_router(src_ip)
        if router is None:
            return False, [src_ip], "no_gateway"

        path = [src_ip]
        cur_src, cur_dst = src_ip, dst_ip
        visited = set()

        for _ in range(max_hops):
            if router in visited:
                return False, path, "routing_loop"
            visited.add(router)
            path.append(router)

            rdata = self.routers[router]

            # 1. Ingress ACL
            acl_key = f"{entry_iface}_in"
            if acl_key in rdata.get("acls", {}):
                verdict = self.eval_acl(rdata["acls"][acl_key], cur_src, cur_dst)
                if verdict == "deny":
                    return False, path, f"acl_denied_at_{router}_{entry_iface}"

            # 2. Check directly-connected destination
            for iname, idata in rdata["interfaces"].items():
                net = network_addr(idata["ip"], idata["prefix"])
                if ip_in_network(cur_dst, net, idata["prefix"]):
                    cur_src, _ = self.apply_snat(router, iname, "out", cur_src, cur_dst)
                    path.append(dst_ip)
                    return True, path, "delivered"

            # 3. Longest-prefix-match routing
            route = self.lpm(router, cur_dst)
            if route is None:
                return False, path, f"no_route_at_{router}"

            if route["rtype"] == "connected":
                # Already handled above (shouldn't reach here)
                path.append(dst_ip)
                return True, path, "delivered"

            nh = route["next_hop"]
            exit_iface = self.resolve_nexthop(router, nh)
            if exit_iface is None:
                return False, path, (
                    f"black_hole_at_{router}_nexthop_{nh}_unreachable"
                )

            # 4. Egress NAT
            cur_src, cur_dst = self.apply_snat(
                router, exit_iface, "out", cur_src, cur_dst
            )

            # 5. Forward to next router
            next_router, next_iface = self._router_by_ip(nh)
            if next_router is None:
                # Next-hop is an unmodeled gateway (e.g. ISP)
                if route["prefix"] == 0:
                    path.append(dst_ip)
                    return True, path, "delivered_via_default"
                return False, path, f"nexthop_{nh}_not_found"

            router = next_router
            entry_iface = next_iface

        return False, path, "max_hops_exceeded"

    # ── misconfiguration detection ─────────────────────────────────

    def detect_misconfigs(self):
        issues = []

        # 1. Black-hole routes: static route with unreachable next-hop
        for rname, fib in self.fibs.items():
            for route in fib:
                if route["rtype"] == "static" and route["next_hop"]:
                    iface = self.resolve_nexthop(rname, route["next_hop"])
                    if iface is None:
                        issues.append({
                            "router": rname,
                            "type": "black_hole",
                            "description": (
                                f"Static route {route['network']}/{route['prefix']} "
                                f"has next-hop {route['next_hop']} which is not "
                                f"reachable on any connected interface of {rname}"
                            ),
                        })

        # 2. ACL shadowing: an earlier rule completely shadows a later rule
        #    of opposite action
        for rname, rdata in self.routers.items():
            for acl_name, rules in rdata.get("acls", {}).items():
                ordered = sorted(rules, key=lambda r: r["id"])
                for i in range(len(ordered)):
                    later = ordered[i]
                    for j in range(i):
                        earlier = ordered[j]
                        if earlier["action"] == later["action"]:
                            continue
                        e_src, e_sp = parse_cidr(earlier["src"])
                        l_src, l_sp = parse_cidr(later["src"])
                        e_dst, e_dp = parse_cidr(earlier["dst"])
                        l_dst, l_dp = parse_cidr(later["dst"])

                        src_shadow = (
                            e_sp <= l_sp
                            and ip_in_network(l_src, e_src, e_sp)
                        )
                        dst_shadow = (
                            e_dp <= l_dp
                            and ip_in_network(l_dst, e_dst, e_dp)
                        )
                        proto_shadow = (
                            earlier.get("protocol", "any") == "any"
                            or earlier.get("protocol") == later.get("protocol")
                        )
                        if src_shadow and dst_shadow and proto_shadow:
                            issues.append({
                                "router": rname,
                                "type": "acl_shadow",
                                "description": (
                                    f"ACL {acl_name}: rule {earlier['id']} "
                                    f"({earlier['action']}) shadows rule "
                                    f"{later['id']} ({later['action']}) — the "
                                    f"later permit rule will never be evaluated"
                                ),
                            })
        return issues

    # ── main entry point ───────────────────────────────────────────

    def run(self):
        self.build_fibs()

        # Reachability for every ordered pair of distinct hosts
        host_ips = [h["ip"] for h in self.hosts.values()]
        reachability = []
        for src in host_ips:
            for dst in host_ips:
                if src == dst:
                    continue
                ok, path, reason = self.trace(src, dst)
                reachability.append({
                    "src": src,
                    "dst": dst,
                    "reachable": ok,
                    "reason": reason,
                })

        misconfigs = self.detect_misconfigs()

        report = {
            "reachability": reachability,
            "misconfigurations": misconfigs,
        }
        with open("/app/report.json", "w") as fh:
            json.dump(report, fh, indent=2)

        print(
            f"Report: {len(reachability)} reachability entries, "
            f"{len(misconfigs)} misconfigurations"
        )


if __name__ == "__main__":
    ReachabilityEngine("/app/topology.json").run()
