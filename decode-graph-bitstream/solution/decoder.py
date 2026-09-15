#!/usr/bin/env python3
"""Decode a WGEF-compressed graph with Elias-Fano offset index and answer queries.

The WGEF format layers:
  1. Header: gamma(N), gamma(W), gamma(K)
  2. Elias-Fano offset index: N cumulative bit offsets
  3. Node data: per-node encoding with copy-list references using zeta_K
"""

import json
import os


class BitReader:
    """Big-endian (MSB-first) bit stream reader."""

    def __init__(self, data):
        self.data = data
        self.byte_pos = 0
        self.bit_pos = 7

    def read_bit(self):
        b = (self.data[self.byte_pos] >> self.bit_pos) & 1
        self.bit_pos -= 1
        if self.bit_pos < 0:
            self.byte_pos += 1
            self.bit_pos = 7
        return b

    def read_bits(self, n):
        val = 0
        for _ in range(n):
            val = (val << 1) | self.read_bit()
        return val

    def read_unary(self):
        count = 0
        while self.read_bit() == 0:
            count += 1
        return count

    def read_gamma(self):
        lam = self.read_unary()
        if lam == 0:
            return 0
        return self.read_bits(lam) + (1 << lam) - 1

    def read_minimal_binary(self, bound):
        if bound <= 0:
            return 0
        s = bound.bit_length() - 1
        threshold = (1 << (s + 1)) - bound
        x = self.read_bits(s)
        if x < threshold:
            return x
        return x * 2 + self.read_bit() - threshold

    def read_zeta(self, k):
        h = self.read_unary()
        l = 1 << (h * k)
        upper = (l << k) - l
        x = self.read_minimal_binary(upper)
        return l + x - 1


def decode_ef(reader, n):
    """Decode an Elias-Fano encoded monotone sequence of n values."""
    if n == 0:
        return []

    L = reader.read_gamma()
    upper_bound = reader.read_gamma()

    # Read lower bits: n values, each L bits
    lowers = []
    for _ in range(n):
        if L > 0:
            lowers.append(reader.read_bits(L))
        else:
            lowers.append(0)

    # Read upper bits: unary-coded gaps
    values = []
    cur_upper = 0
    for i in range(n):
        gap = reader.read_unary()
        cur_upper += gap
        values.append((cur_upper << L) | lowers[i])

    return values


def decode_graph(path):
    """Decode the full WGEF compressed graph."""
    with open(path, "rb") as f:
        data = f.read()

    assert data[:4] == b"WGEF", f"Bad magic: {data[:4]!r}"

    reader = BitReader(data[4:])

    # Header
    n_nodes = reader.read_gamma()
    window = reader.read_gamma()
    zeta_k = reader.read_gamma()

    # Elias-Fano offset index (decode and consume, offsets not needed
    # for sequential decoding but we must advance past this section)
    offsets = decode_ef(reader, n_nodes)

    # Node data
    adj = [[] for _ in range(n_nodes)]

    for u in range(n_nodes):
        deg = reader.read_gamma()
        if deg == 0:
            continue

        ref_offset = reader.read_gamma()

        if ref_offset > 0:
            # Copy-list mode
            ref_node = u - ref_offset
            ref_succs = adj[ref_node]

            block_count = reader.read_gamma()
            blocks = [reader.read_gamma() for _ in range(block_count)]

            # Apply copy/skip blocks
            copied = []
            idx = 0
            is_copy = True
            for b in blocks:
                if is_copy:
                    for j in range(b):
                        if idx + j < len(ref_succs):
                            copied.append(ref_succs[idx + j])
                idx += b
                is_copy = not is_copy

            # Read extra successors
            extra_count = reader.read_gamma()
            extras = []
            if extra_count > 0:
                s = reader.read_zeta(zeta_k)
                extras.append(s)
                for _ in range(extra_count - 1):
                    gap = reader.read_zeta(zeta_k)
                    s = s + gap + 1
                    extras.append(s)

            adj[u] = sorted(copied + extras)
        else:
            # Direct mode
            s = reader.read_zeta(zeta_k)
            adj[u].append(s)
            for _ in range(deg - 1):
                gap = reader.read_zeta(zeta_k)
                s = s + gap + 1
                adj[u].append(s)

    return n_nodes, adj


def answer_queries(n_nodes, adj, queries):
    """Compute answers for all queries."""
    # Precompute in-degrees
    in_deg = [0] * n_nodes
    for u in range(n_nodes):
        for v in adj[u]:
            in_deg[v] += 1

    answers = []
    for q in queries:
        parts = q.split()
        cmd = parts[0]

        if cmd == "NODES":
            answers.append(str(n_nodes))
        elif cmd == "EDGES":
            answers.append(str(sum(len(a) for a in adj)))
        elif cmd == "OUTDEGREE":
            answers.append(str(len(adj[int(parts[1])])))
        elif cmd == "EDGE":
            u, v = int(parts[1]), int(parts[2])
            answers.append("1" if v in adj[u] else "0")
        elif cmd == "SUCCESSORS":
            node = int(parts[1])
            if adj[node]:
                answers.append(" ".join(str(s) for s in adj[node]))
            else:
                answers.append("NONE")
        elif cmd == "MAX_DEGREE":
            answers.append(str(max(len(a) for a in adj)))
        elif cmd == "ISOLATED_NODES":
            answers.append(str(sum(1 for a in adj if len(a) == 0)))
        elif cmd == "FIRST_SUCCESSOR_SUM":
            answers.append(str(sum(a[0] for a in adj if a)))
        elif cmd == "IN_DEGREE":
            answers.append(str(in_deg[int(parts[1])]))
        elif cmd == "CHECKSUM":
            cs = 0
            for u in range(n_nodes):
                for v in adj[u]:
                    cs ^= (u * 31337 + v)
            answers.append(str(cs))
        elif cmd == "TWO_HOP_REACH":
            node = int(parts[1])
            reachable = set()
            for v in adj[node]:
                reachable.add(v)
                for w in adj[v]:
                    reachable.add(w)
            reachable.discard(node)
            answers.append(str(len(reachable)))

    return answers


def main():
    n_nodes, adj = decode_graph("/app/data/graph.bin")

    os.makedirs("/app/output", exist_ok=True)

    with open("/app/output/adjacency.json", "w") as f:
        json.dump(adj, f)

    with open("/app/data/queries.txt") as f:
        queries = [line.strip() for line in f if line.strip()]

    answers = answer_queries(n_nodes, adj, queries)

    with open("/app/output/answers.txt", "w") as f:
        for a in answers:
            f.write(a + "\n")


if __name__ == "__main__":
    main()
