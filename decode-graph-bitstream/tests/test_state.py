
"""Verification tests for the WGEF graph decoding task.

Verifies correctness by re-encoding the agent's decoded adjacency lists
using the same compression algorithm (including the Elias-Fano offset
index) and comparing byte-for-byte against the original binary. No
reference answers are stored.
"""

import json
import math
import os

import pytest

MAGIC = b"WGEF"


# =====================================================================
# Encoder (re-encoding for round-trip verification)
# =====================================================================

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

    def read_bit(self):
        b = (self.data[self.byte_pos] >> self.bit_pos) & 1
        self.bit_pos -= 1
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


def _ef_encode(writer, values, n):
    """Encode a sorted sequence using Elias-Fano representation."""
    if n == 0:
        return
    upper_bound = values[-1] + 1
    if upper_bound > n:
        L = (upper_bound // n).bit_length() - 1
    else:
        L = 0
    writer.write_gamma(L)
    writer.write_gamma(upper_bound)
    mask = (1 << L) - 1 if L > 0 else 0
    for v in values:
        if L > 0:
            writer.write_bits(v & mask, L)
    prev_upper = 0
    for v in values:
        cur_upper = v >> L
        gap = cur_upper - prev_upper
        writer.write_unary(gap)
        prev_upper = cur_upper


def _compute_copy_blocks(ref_succs, target_succs):
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


def _find_best_reference(u, adj, window):
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

        blocks, extras = _compute_copy_blocks(adj[ref_node], adj[u])
        copied_count = len(adj[u]) - len(extras)
        score = copied_count * 3 - len(blocks) * 2 - 3

        if score > best_score:
            best_score = score
            best_offset = offset
            best_blocks = blocks
            best_extras = extras

    return best_offset, best_blocks, best_extras


def _encode_node(w, u, adj, ref_offset, blocks, extras, k):
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
                w.write_zeta(gap, k)
    else:
        w.write_zeta(adj[u][0], k)
        for i in range(1, deg):
            gap = adj[u][i] - adj[u][i - 1] - 1
            w.write_zeta(gap, k)


def _read_header(data):
    """Read N, W, K from the binary header."""
    r = BitReader(data)
    N = r.read_gamma()
    W = r.read_gamma()
    K = r.read_gamma()
    return N, W, K


def _encode_graph(adj, window, k):
    """Full encode: header + EF offset index + node data."""
    n_nodes = len(adj)

    # Pre-compute encoding decisions
    plans = []
    for u in range(n_nodes):
        ref_offset, blocks, extras = _find_best_reference(u, adj, window)
        plans.append((ref_offset, blocks, extras))

    # Compute per-node bit lengths
    node_bit_counts = []
    for u in range(n_nodes):
        tmp = BitWriter()
        ref_offset, blocks, extras = plans[u]
        _encode_node(tmp, u, adj, ref_offset, blocks, extras, k)
        node_bit_counts.append(tmp.total_bits)

    # Cumulative offsets
    offsets = [0]
    for i in range(n_nodes - 1):
        offsets.append(offsets[-1] + node_bit_counts[i])

    # Build full binary
    w = BitWriter()
    w.write_gamma(n_nodes)
    w.write_gamma(window)
    w.write_gamma(k)
    _ef_encode(w, offsets, n_nodes)
    for u in range(n_nodes):
        ref_offset, blocks, extras = plans[u]
        _encode_node(w, u, adj, ref_offset, blocks, extras, k)

    return w.flush()


# =====================================================================
# Query answer computation
# =====================================================================

def _compute_answer(adj, query):
    parts = query.split()
    cmd = parts[0]
    n_nodes = len(adj)

    if cmd == "NODES":
        return str(n_nodes)
    elif cmd == "EDGES":
        return str(sum(len(a) for a in adj))
    elif cmd == "OUTDEGREE":
        return str(len(adj[int(parts[1])]))
    elif cmd == "EDGE":
        u, v = int(parts[1]), int(parts[2])
        return "1" if v in adj[u] else "0"
    elif cmd == "SUCCESSORS":
        node = int(parts[1])
        return " ".join(str(s) for s in adj[node]) if adj[node] else "NONE"
    elif cmd == "MAX_DEGREE":
        return str(max(len(a) for a in adj))
    elif cmd == "ISOLATED_NODES":
        return str(sum(1 for a in adj if len(a) == 0))
    elif cmd == "FIRST_SUCCESSOR_SUM":
        return str(sum(a[0] for a in adj if a))
    elif cmd == "IN_DEGREE":
        target = int(parts[1])
        return str(sum(1 for a in adj for v in a if v == target))
    elif cmd == "CHECKSUM":
        cs = 0
        for u in range(n_nodes):
            for v in adj[u]:
                cs ^= (u * 31337 + v)
        return str(cs)
    elif cmd == "TWO_HOP_REACH":
        node = int(parts[1])
        reachable = set()
        for v in adj[node]:
            reachable.add(v)
            for w in adj[v]:
                reachable.add(w)
        reachable.discard(node)
        return str(len(reachable))
    return ""


# =====================================================================
# Loaders
# =====================================================================

def _load_adjacency():
    with open("/app/output/adjacency.json") as f:
        return json.load(f)


def _load_answers():
    with open("/app/output/answers.txt") as f:
        return [line.strip() for line in f if line.strip()]


def _load_queries():
    with open("/app/data/queries.txt") as f:
        return [q.strip() for q in f if q.strip()]


def _load_original_binary():
    with open("/app/data/graph.bin", "rb") as f:
        return f.read()


# =====================================================================
# Tests
# =====================================================================

class TestOutputExists:
    def test_adjacency_file_exists(self):
        assert os.path.exists("/app/output/adjacency.json"), (
            "Missing /app/output/adjacency.json"
        )

    def test_answers_file_exists(self):
        assert os.path.exists("/app/output/answers.txt"), (
            "Missing /app/output/answers.txt"
        )


class TestAdjacencyStructure:
    def test_is_list_of_lists(self):
        adj = _load_adjacency()
        assert isinstance(adj, list), "adjacency.json must be a JSON array"
        for i, succs in enumerate(adj):
            assert isinstance(succs, list), f"Node {i}: successor list must be an array"

    def test_successors_sorted_and_unique(self):
        adj = _load_adjacency()
        for i, succs in enumerate(adj):
            assert succs == sorted(set(succs)), (
                f"Node {i}: successors must be sorted with no duplicates"
            )

    def test_successor_ids_in_range(self):
        adj = _load_adjacency()
        n = len(adj)
        for i, succs in enumerate(adj):
            for s in succs:
                assert 0 <= s < n, (
                    f"Node {i}: successor {s} out of range [0, {n})"
                )


class TestRoundTrip:
    """Re-encode the decoded adjacency lists and compare with the original binary."""

    def test_round_trip_binary_match(self):
        adj = _load_adjacency()
        original = _load_original_binary()

        # Read header parameters from original binary
        N, W, K = _read_header(original[4:])
        assert len(adj) == N, (
            f"Node count mismatch: adjacency has {len(adj)} nodes, header says {N}"
        )

        re_encoded = _encode_graph(adj, W, K)
        assert MAGIC + re_encoded == original, (
            f"Round-trip encoding mismatch: re-encoded {len(MAGIC) + len(re_encoded)} bytes "
            f"vs original {len(original)} bytes. The decoded adjacency lists do not "
            f"reproduce the original compressed binary."
        )


class TestQueryAnswers:
    def test_answer_count(self):
        queries = _load_queries()
        answers = _load_answers()
        assert len(answers) == len(queries), (
            f"Expected {len(queries)} answers, got {len(answers)}"
        )

    def test_all_answers_consistent(self):
        adj = _load_adjacency()
        queries = _load_queries()
        answers = _load_answers()
        for i, q in enumerate(queries):
            expected = _compute_answer(adj, q)
            assert answers[i] == expected, (
                f"Query '{q}': expected '{expected}', got '{answers[i]}'"
            )
