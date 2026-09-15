#!/usr/bin/env python3
"""Generate a WGEF-compressed graph with Elias-Fano offset index.

Format:
  [4 bytes: MAGIC "WGEF"]
  [Header: gamma(N), gamma(W), gamma(K)]
  [Elias-Fano offset index: N cumulative bit offsets into node data]
  [Node data: per-node encoding with copy-list references using zeta_K]
"""

import json
import math
import os
import random
import sys

SEED = 0xDEADBEEF
N = 600
P_BASE = 0.012
WINDOW = 7
ZETA_K = 5
MAGIC = b"WGEF"
COPY_PROB = 0.35


class BitWriter:
    """Big-endian (MSB-first) bit stream writer."""

    def __init__(self):
        self.data = bytearray()
        self.current = 0
        self.pos = 7
        self.total_bits = 0

    def write_bit(self, b):
        if b:
            self.current |= (1 << self.pos)
        self.pos -= 1
        self.total_bits += 1
        if self.pos < 0:
            self.data.append(self.current)
            self.current = 0
            self.pos = 7

    def write_bits(self, val, n):
        for i in range(n - 1, -1, -1):
            self.write_bit((val >> i) & 1)

    def write_unary(self, n):
        for _ in range(n):
            self.write_bit(0)
        self.write_bit(1)

    def write_gamma(self, n):
        m = n + 1
        lam = m.bit_length() - 1
        self.write_unary(lam)
        if lam > 0:
            self.write_bits(m ^ (1 << lam), lam)

    def write_minimal_binary(self, x, bound):
        if bound <= 0:
            return
        s = bound.bit_length() - 1
        threshold = (1 << (s + 1)) - bound
        if x < threshold:
            self.write_bits(x, s)
        else:
            self.write_bits(x + threshold, s + 1)

    def write_zeta(self, n, k):
        m = n + 1
        lam = m.bit_length() - 1
        h = lam // k
        l = 1 << (h * k)
        self.write_unary(h)
        upper = (l << k) - l
        self.write_minimal_binary(m - l, upper)

    def flush(self):
        if self.pos < 7:
            self.data.append(self.current)
        return bytes(self.data)


class BitReader:
    """Big-endian (MSB-first) bit stream reader."""

    def __init__(self, data):
        self.data = data
        self.byte_pos = 0
        self.bit_pos = 7
        self.total_bits_read = 0

    def read_bit(self):
        b = (self.data[self.byte_pos] >> self.bit_pos) & 1
        self.bit_pos -= 1
        self.total_bits_read += 1
        if self.bit_pos < 0:
            self.byte_pos += 1
            self.bit_pos = 7
        return b

    def read_bits(self, n):
        v = 0
        for _ in range(n):
            v = (v << 1) | self.read_bit()
        return v

    def read_unary(self):
        c = 0
        while self.read_bit() == 0:
            c += 1
        return c

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


def ef_encode(writer, values, n):
    """Encode a sorted sequence using Elias-Fano representation.

    Stores lower L bits packed contiguously, then upper bits as unary gaps.
    """
    if n == 0:
        return

    upper_bound = values[-1] + 1  # exclusive

    if upper_bound > n:
        L = (upper_bound // n).bit_length() - 1
    else:
        L = 0

    writer.write_gamma(L)
    writer.write_gamma(upper_bound)

    # Lower bits: N values, each L bits wide
    mask = (1 << L) - 1 if L > 0 else 0
    for v in values:
        if L > 0:
            writer.write_bits(v & mask, L)

    # Upper bits: unary-coded gaps of (v >> L)
    prev_upper = 0
    for v in values:
        cur_upper = v >> L
        gap = cur_upper - prev_upper
        writer.write_unary(gap)
        prev_upper = cur_upper


def ef_decode(reader, n):
    """Decode an Elias-Fano encoded sequence."""
    if n == 0:
        return []

    L = reader.read_gamma()
    upper_bound = reader.read_gamma()

    lowers = []
    for _ in range(n):
        if L > 0:
            lowers.append(reader.read_bits(L))
        else:
            lowers.append(0)

    values = []
    cur_upper = 0
    for i in range(n):
        gap = reader.read_unary()
        cur_upper += gap
        values.append((cur_upper << L) | lowers[i])

    return values


def compute_copy_blocks(ref_succs, target_succs):
    """Compute copy/skip block encoding for target based on ref."""
    target_set = set(target_succs)
    flags = [s in target_set for s in ref_succs]

    blocks = []
    i = 0
    is_copy = True
    while i < len(flags):
        count = 0
        while i < len(flags) and flags[i] == is_copy:
            count += 1
            i += 1
        blocks.append(count)
        is_copy = not is_copy

    if not blocks:
        blocks = [0]

    # Trim trailing zero-copy and trailing skip blocks
    while len(blocks) > 1 and (len(blocks) % 2 == 0 or blocks[-1] == 0):
        blocks.pop()

    copied = []
    idx = 0
    is_copy_flag = True
    for b in blocks:
        if is_copy_flag:
            for j in range(b):
                if idx + j < len(ref_succs):
                    copied.append(ref_succs[idx + j])
        idx += b
        is_copy_flag = not is_copy_flag

    extras = sorted(s for s in target_succs if s not in set(copied))
    return blocks, extras


def find_best_reference(u, adj, window):
    """Find the best reference node for copy-mode encoding."""
    if not adj[u]:
        return 0, [], []

    best_offset = 0
    best_blocks = []
    best_extras = list(adj[u])
    best_score = -1

    for offset in range(1, min(window + 1, u + 1)):
        ref_node = u - offset
        if not adj[ref_node]:
            continue

        blocks, extras = compute_copy_blocks(adj[ref_node], adj[u])
        copied_count = len(adj[u]) - len(extras)
        score = copied_count * 3 - len(blocks) * 2 - 3

        if score > best_score:
            best_score = score
            best_offset = offset
            best_blocks = blocks
            best_extras = extras

    return best_offset, best_blocks, best_extras


def encode_node(w, u, adj, ref_offset, blocks, extras, k):
    """Encode a single node's data into the writer."""
    deg = len(adj[u])
    w.write_gamma(deg)
    if deg == 0:
        return
    w.write_gamma(ref_offset)
    if ref_offset > 0:
        w.write_gamma(len(blocks))
        for b in blocks:
            w.write_gamma(b)
        w.write_gamma(len(extras))
        if extras:
            w.write_zeta(extras[0], k)
            for i in range(1, len(extras)):
                gap = extras[i] - extras[i - 1] - 1
                assert gap >= 0
                w.write_zeta(gap, k)
    else:
        w.write_zeta(adj[u][0], k)
        for i in range(1, deg):
            gap = adj[u][i] - adj[u][i - 1] - 1
            assert gap >= 0
            w.write_zeta(gap, k)


def main():
    random.seed(SEED)

    # Generate directed graph
    adj = [[] for _ in range(N)]
    for u in range(N):
        for v in range(N):
            if u != v and random.random() < P_BASE:
                adj[u].append(v)

    # Add copy-like structure: some nodes derive successors from nearby nodes
    for u in range(1, N):
        if random.random() < COPY_PROB:
            ref = u - random.randint(1, min(WINDOW, u))
            if adj[ref]:
                new_succs = set(adj[ref])
                remove_count = min(len(new_succs) // 4, random.randint(0, 3))
                if remove_count > 0:
                    to_remove = random.sample(sorted(new_succs), remove_count)
                    new_succs -= set(to_remove)
                for _ in range(random.randint(1, 5)):
                    v = random.randint(0, N - 1)
                    if v != u:
                        new_succs.add(v)
                new_succs.discard(u)
                adj[u] = sorted(new_succs)

    # Pre-compute encoding decisions for each node
    plans = []
    for u in range(N):
        ref_offset, blocks, extras = find_best_reference(u, adj, WINDOW)
        plans.append((ref_offset, blocks, extras))

    # First pass: compute per-node bit lengths
    node_bit_counts = []
    for u in range(N):
        tmp = BitWriter()
        ref_offset, blocks, extras = plans[u]
        encode_node(tmp, u, adj, ref_offset, blocks, extras, ZETA_K)
        node_bit_counts.append(tmp.total_bits)

    # Compute cumulative bit offsets for the EF index
    offsets = [0]
    for i in range(N - 1):
        offsets.append(offsets[-1] + node_bit_counts[i])

    # Build the full binary: header + EF index + node data
    w = BitWriter()

    # Header
    w.write_gamma(N)
    w.write_gamma(WINDOW)
    w.write_gamma(ZETA_K)

    # Elias-Fano offset index
    ef_encode(w, offsets, N)

    # Node data
    for u in range(N):
        ref_offset, blocks, extras = plans[u]
        encode_node(w, u, adj, ref_offset, blocks, extras, ZETA_K)

    binary_data = MAGIC + w.flush()

    # Verify by full round-trip decode
    r = BitReader(binary_data[4:])
    n_check = r.read_gamma()
    w_check = r.read_gamma()
    k_check = r.read_gamma()
    assert n_check == N
    assert w_check == WINDOW
    assert k_check == ZETA_K

    offsets_check = ef_decode(r, N)
    assert offsets_check == offsets, "EF offset mismatch"

    adj_check = [[] for _ in range(N)]
    for u in range(N):
        deg = r.read_gamma()
        if deg == 0:
            continue
        ref_off = r.read_gamma()
        if ref_off > 0:
            ref_succs = adj_check[u - ref_off]
            block_count = r.read_gamma()
            block_list = [r.read_gamma() for _ in range(block_count)]
            copied = []
            idx = 0
            is_copy = True
            for b in block_list:
                if is_copy:
                    for j in range(b):
                        if idx + j < len(ref_succs):
                            copied.append(ref_succs[idx + j])
                idx += b
                is_copy = not is_copy
            extra_count = r.read_gamma()
            extra_list = []
            if extra_count > 0:
                s = r.read_zeta(ZETA_K)
                extra_list.append(s)
                for _ in range(extra_count - 1):
                    gap = r.read_zeta(ZETA_K)
                    s = s + gap + 1
                    extra_list.append(s)
            adj_check[u] = sorted(copied + extra_list)
        else:
            s = r.read_zeta(ZETA_K)
            adj_check[u].append(s)
            for _ in range(deg - 1):
                gap = r.read_zeta(ZETA_K)
                s = s + gap + 1
                adj_check[u].append(s)
        assert len(adj_check[u]) == deg, f"Node {u}: {len(adj_check[u])} != {deg}"

    for u in range(N):
        assert adj_check[u] == adj[u], f"Mismatch at node {u}"

    total_edges = sum(len(a) for a in adj)
    copy_count = sum(1 for ro, _, _ in plans if ro > 0)
    print(
        f"Verified: {N} nodes, {total_edges} edges, {len(binary_data)} bytes, "
        f"{copy_count} copy-mode nodes",
        file=sys.stderr,
    )

    # Write output files
    os.makedirs("/app/data", exist_ok=True)
    with open("/app/data/graph.bin", "wb") as f:
        f.write(binary_data)

    # Generate queries
    queries = ["NODES", "EDGES"]
    for v in [0, 42, 100, 300, 599]:
        queries.append(f"OUTDEGREE {v}")
    for u_q in [0, 42, 100]:
        if adj[u_q]:
            queries.append(f"EDGE {u_q} {adj[u_q][0]}")
            if len(adj[u_q]) > 1:
                queries.append(f"EDGE {u_q} {adj[u_q][-1]}")
    queries.extend(["EDGE 0 1", "EDGE 599 0"])
    for v in [0, 42, 300]:
        queries.append(f"SUCCESSORS {v}")
    queries.extend([
        "MAX_DEGREE",
        "ISOLATED_NODES",
        "FIRST_SUCCESSOR_SUM",
        "IN_DEGREE 42",
        "IN_DEGREE 300",
        "CHECKSUM",
        "TWO_HOP_REACH 42",
        "TWO_HOP_REACH 100",
    ])

    with open("/app/data/queries.txt", "w") as f:
        for q in queries:
            f.write(q + "\n")

    print(f"Generated {len(queries)} queries", file=sys.stderr)


if __name__ == "__main__":
    main()
