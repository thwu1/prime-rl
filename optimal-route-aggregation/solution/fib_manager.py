#!/usr/bin/env python3
"""IPv4 FIB Manager with ORTC Optimal Route Aggregation.

Reads INSERT/DELETE/LOOKUP/AGGREGATE operations from stdin.
Implements the Optimal Routing Table Constructor (Draves et al. 1999)
for provably minimal route aggregation.
"""

import sys

NONE = -1  # sentinel: no child / no nexthop


def ip_to_int(s):
    a, b, c, d = s.split(".")
    return (int(a) << 24) | (int(b) << 16) | (int(c) << 8) | int(d)


def int_to_ip(v):
    return f"{(v >> 24) & 0xFF}.{(v >> 16) & 0xFF}.{(v >> 8) & 0xFF}.{v & 0xFF}"


def parse_prefix(s):
    ip, ln = s.split("/")
    return ip_to_int(ip), int(ln)


class FIBManager:
    def __init__(self):
        self.routes = {}  # (prefix_int, prefix_len) -> nexthop
        # Trie: list of [left_child, right_child, nexthop]
        self._trie = [[NONE, NONE, NONE]]

    def _new_node(self):
        idx = len(self._trie)
        self._trie.append([NONE, NONE, NONE])
        return idx

    def _rebuild_trie(self):
        self._trie = [[NONE, NONE, NONE]]
        for (pi, pl), nh in self.routes.items():
            self._trie_insert(pi, pl, nh)

    def _trie_insert(self, pi, pl, nh):
        node = 0
        for i in range(pl):
            bit = (pi >> (31 - i)) & 1
            child = self._trie[node][bit]
            if child == NONE:
                child = self._new_node()
                self._trie[node][bit] = child
            node = child
        self._trie[node][2] = nh

    def insert(self, prefix, nh):
        pi, pl = parse_prefix(prefix)
        self.routes[(pi, pl)] = nh
        self._trie_insert(pi, pl, nh)

    def delete(self, prefix):
        pi, pl = parse_prefix(prefix)
        if (pi, pl) in self.routes:
            del self.routes[(pi, pl)]
            self._rebuild_trie()

    def lookup(self, ip_str):
        ip = ip_to_int(ip_str)
        node = 0
        best = self._trie[0][2]
        for i in range(32):
            bit = (ip >> (31 - i)) & 1
            child = self._trie[node][bit]
            if child == NONE:
                break
            node = child
            if self._trie[node][2] != NONE:
                best = self._trie[node][2]
        return best

    def aggregate(self):
        """ORTC optimal route aggregation."""
        if not self.routes:
            return []

        # Build fresh trie (don't modify the lookup trie)
        T = [[NONE, NONE, NONE]]

        def nn():
            idx = len(T)
            T.append([NONE, NONE, NONE])
            return idx

        for (pi, pl), nh in self.routes.items():
            n = 0
            for i in range(pl):
                b = (pi >> (31 - i)) & 1
                c = T[n][b]
                if c == NONE:
                    c = nn()
                    T[n][b] = c
                n = c
            T[n][2] = nh

        # --- Phase 1: Normalize ---
        # Ensure every internal node has exactly two children.
        # Missing children become leaves inheriting the effective nexthop.
        stack = [(0, NONE)]
        while stack:
            n, inh = stack.pop()
            eff = T[n][2] if T[n][2] != NONE else inh
            l, r = T[n][0], T[n][1]
            if l != NONE or r != NONE:
                if l == NONE:
                    l = nn()
                    T[l][2] = eff
                    T[n][0] = l
                if r == NONE:
                    r = nn()
                    T[r][2] = eff
                    T[n][1] = r
                stack.append((r, eff))
                stack.append((l, eff))

        # --- Phase 2: Bottom-up nexthop-set computation ---
        # Leaf: nh_set = {nexthop}
        # Internal: if either child has NONE (uncovered addresses), force {NONE}
        # (we cannot emit routes that cover addresses meant to be unreachable,
        # since we have no "discard/blackhole" route mechanism).
        # Otherwise: intersection of children if non-empty, else union.
        _NONE_SET = frozenset([NONE])
        num = len(T)
        nh_sets = [None] * num

        pstack = [(0, False)]
        while pstack:
            n, done = pstack.pop()
            l, r = T[n][0], T[n][1]
            if l == NONE:  # leaf
                nh_sets[n] = frozenset([T[n][2]])
                continue
            if done:
                if NONE in nh_sets[l] or NONE in nh_sets[r]:
                    nh_sets[n] = _NONE_SET
                else:
                    inter = nh_sets[l] & nh_sets[r]
                    nh_sets[n] = inter if inter else nh_sets[l] | nh_sets[r]
            else:
                pstack.append((n, True))
                pstack.append((r, False))
                pstack.append((l, False))

        # --- Phase 3: Top-down optimal selection ---
        # If the inherited nexthop is in the nh_set, use it (no new entry).
        # Otherwise pick any from nh_set and emit a route entry.
        result = []
        sstack = [(0, NONE, 0, 0)]  # (node, inherited, depth, prefix_int)
        while sstack:
            n, inh, dep, pfx = sstack.pop()
            ns = nh_sets[n]
            if inh in ns:
                ch = inh
            else:
                ch = next(iter(ns))
                if ch != NONE:
                    result.append((pfx, dep, ch))
            l, r = T[n][0], T[n][1]
            if l != NONE:
                sstack.append((r, ch, dep + 1, pfx | (1 << (31 - dep))))
                sstack.append((l, ch, dep + 1, pfx))

        result.sort()
        return result


def main():
    fib = FIBManager()
    out = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        cmd = parts[0]
        if cmd == "INSERT":
            fib.insert(parts[1], int(parts[2]))
        elif cmd == "DELETE":
            fib.delete(parts[1])
        elif cmd == "LOOKUP":
            r = fib.lookup(parts[1])
            out.append("NONE" if r == NONE else str(r))
        elif cmd == "AGGREGATE":
            entries = fib.aggregate()
            out.append(str(len(entries)))
            for pi, pl, nh in entries:
                out.append(f"{int_to_ip(pi)}/{pl} {nh}")

    sys.stdout.write("\n".join(out))
    if out:
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
