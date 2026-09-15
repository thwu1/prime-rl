"""
"""
import pytest
import os
from collections import defaultdict
import heapq


def load_initial_graph():
    """Load the initial edge list from CSV."""
    edges = []
    with open('/data/initial_edges.csv') as f:
        f.readline()  # skip header
        for line in f:
            line = line.strip()
            if line:
                u, v = line.split(',')
                edges.append((int(u), int(v)))
    return edges


def load_operations():
    """Load operations grouped by batch_id."""
    batches = defaultdict(list)
    with open('/data/operations.csv') as f:
        f.readline()  # skip header
        for line in f:
            line = line.strip()
            if line:
                parts = line.split(',')
                batch_id = int(parts[0])
                op = parts[1]
                u, v = int(parts[2]), int(parts[3])
                batches[batch_id].append((op, u, v))
    return batches


def build_adj(edges):
    """Build adjacency sets from edge list."""
    adj = defaultdict(set)
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)
    return adj


def count_triangles_full(adj):
    """Count triangles by full enumeration: iterate edges, count common neighbors."""
    total = 0
    for u in adj:
        for v in adj[u]:
            if v > u:
                total += len(adj[u] & adj[v])
    # Each triangle is counted 3 times (once per edge)
    return total // 3


def count_per_node_triangles_full(adj):
    """Count per-node triangle participation via full enumeration."""
    tri = defaultdict(int)
    for u in adj:
        for v in adj[u]:
            if v > u:
                common = adj[u] & adj[v]
                for w in common:
                    tri[u] += 1
                    tri[v] += 1
                    tri[w] += 1
    # Each triangle found at 3 edges; each time all 3 nodes incremented => /3
    result = {}
    for node, count in tri.items():
        c = count // 3
        if c > 0:
            result[node] = c
    return result


def compute_truss_decomposition(edges):
    """Compute truss number for each edge via support peeling."""
    adj = defaultdict(set)
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)

    # Compute initial support (triangle count per edge)
    support = {}
    for u, v in edges:
        support[(u, v)] = len(adj[u] & adj[v])

    remaining = set(edges)
    truss_num = {}

    pq = [(support[e], e) for e in edges]
    heapq.heapify(pq)

    k = 2
    while pq:
        s, e = heapq.heappop(pq)
        if e not in remaining:
            continue
        if support[e] != s:
            continue  # stale entry

        k = max(k, s + 2)
        truss_num[e] = k

        u, v = e
        common = adj[u] & adj[v]
        for w in common:
            e1 = (min(u, w), max(u, w))
            e2 = (min(v, w), max(v, w))
            if e1 in remaining:
                support[e1] -= 1
                heapq.heappush(pq, (support[e1], e1))
            if e2 in remaining:
                support[e2] -= 1
                heapq.heappush(pq, (support[e2], e2))

        adj[u].discard(v)
        adj[v].discard(u)
        remaining.discard(e)

    return truss_num


@pytest.fixture(scope='module')
def reference_data():
    """Compute all reference results for verification."""
    initial_edges = load_initial_graph()
    operations = load_operations()

    # Build adjacency and replay all operations using delta queries
    adj = build_adj(initial_edges)
    edge_set = set(initial_edges)

    # Initial triangle count via full enumeration
    total_tri = count_triangles_full(adj)

    # Process batches with delta queries, verify at checkpoints
    expected_tri_counts = {}
    num_batches = 300
    checkpoint_batches = {50, 100, 150, 200, 250}

    for batch_id in range(num_batches):
        ops = operations.get(batch_id, [])
        for op, u, v in ops:
            common = adj[u] & adj[v]
            delta = len(common)
            if op == '+':
                total_tri += delta
                adj[u].add(v)
                adj[v].add(u)
                edge_set.add((u, v))
            else:
                total_tri -= delta
                adj[u].discard(v)
                adj[v].discard(u)
                edge_set.discard((u, v))
        expected_tri_counts[batch_id] = total_tri

        # Cross-validate delta computation at checkpoints
        if batch_id in checkpoint_batches:
            full = count_triangles_full(adj)
            assert full == total_tri, (
                f"Internal check: delta mismatch at batch {batch_id}: "
                f"delta={total_tri}, full={full}"
            )

    # Final full-count verification
    full_final = count_triangles_full(adj)
    assert full_final == total_tri, (
        f"Internal check: final delta mismatch: delta={total_tri}, full={full_final}"
    )

    # Per-node triangles on final graph
    expected_node_tri = count_per_node_triangles_full(adj)

    # Truss decomposition on final graph
    final_edges = sorted(edge_set)
    expected_truss = compute_truss_decomposition(final_edges)

    return {
        'expected_tri_counts': expected_tri_counts,
        'expected_node_tri': expected_node_tri,
        'expected_truss': expected_truss,
        'num_batches': num_batches,
        'final_total_tri': total_tri,
    }


class TestTriangleCounts:
    def test_output_file_exists(self):
        assert os.path.isfile('/app/output/triangle_counts.txt'), \
            "Missing /app/output/triangle_counts.txt"

    def test_correct_line_count(self):
        with open('/app/output/triangle_counts.txt') as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 300, f"Expected 300 lines, got {len(lines)}"

    def test_triangle_counts_correct(self, reference_data):
        expected = reference_data['expected_tri_counts']
        with open('/app/output/triangle_counts.txt') as f:
            lines = [l.strip() for l in f if l.strip()]

        errors = []
        for line in lines:
            parts = line.split()
            batch_id = int(parts[0])
            count = int(parts[1])
            if batch_id in expected and count != expected[batch_id]:
                errors.append(
                    f"Batch {batch_id}: expected {expected[batch_id]}, got {count}"
                )

        assert len(errors) == 0, (
            f"Triangle count errors ({len(errors)} batches wrong):\n"
            + "\n".join(errors[:20])
        )

    def test_batch_ids_sequential(self):
        with open('/app/output/triangle_counts.txt') as f:
            lines = [l.strip() for l in f if l.strip()]
        ids = [int(l.split()[0]) for l in lines]
        assert ids == list(range(300)), "Batch IDs must be 0 through 299 in order"


class TestNodeTriangles:
    def test_output_file_exists(self):
        assert os.path.isfile('/app/output/node_triangles.txt'), \
            "Missing /app/output/node_triangles.txt"

    def test_node_triangles_correct(self, reference_data):
        expected = reference_data['expected_node_tri']

        actual = {}
        with open('/app/output/node_triangles.txt') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    node_id = int(parts[0])
                    count = int(parts[1])
                    if count > 0:
                        actual[node_id] = count

        missing = set(expected.keys()) - set(actual.keys())
        extra = set(actual.keys()) - set(expected.keys())
        wrong = {
            n for n in (set(expected.keys()) & set(actual.keys()))
            if expected[n] != actual[n]
        }

        errors = []
        for n in sorted(missing)[:10]:
            errors.append(f"Missing node {n} (expected count {expected[n]})")
        for n in sorted(extra)[:10]:
            errors.append(f"Extra node {n} (got count {actual[n]})")
        for n in sorted(wrong)[:10]:
            errors.append(
                f"Node {n}: expected {expected[n]}, got {actual[n]}"
            )

        assert len(errors) == 0, (
            f"Node triangle errors ({len(missing)} missing, {len(extra)} extra, "
            f"{len(wrong)} wrong values):\n" + "\n".join(errors)
        )

    def test_per_node_sum_consistency(self, reference_data):
        """Per-node counts must sum to 3 * total_triangles in the final graph."""
        actual = {}
        with open('/app/output/node_triangles.txt') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    actual[int(parts[0])] = int(parts[1])

        actual_sum = sum(actual.values())

        with open('/app/output/triangle_counts.txt') as f:
            lines = [l.strip() for l in f if l.strip()]
        final_tri = int(lines[-1].split()[1])

        assert actual_sum == 3 * final_tri, (
            f"Sum of per-node counts ({actual_sum}) != "
            f"3 * final triangle count ({3 * final_tri})"
        )

    def test_sorted_by_node_id(self):
        ids = []
        with open('/app/output/node_triangles.txt') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    ids.append(int(parts[0]))
        assert ids == sorted(ids), "Node triangle output must be sorted by node_id"


class TestTrussDecomposition:
    def test_output_file_exists(self):
        assert os.path.isfile('/app/output/truss_decomposition.txt'), \
            "Missing /app/output/truss_decomposition.txt"

    def test_truss_edge_count(self, reference_data):
        expected_count = len(reference_data['expected_truss'])
        actual_count = 0
        with open('/app/output/truss_decomposition.txt') as f:
            for line in f:
                if line.strip():
                    actual_count += 1
        assert actual_count == expected_count, (
            f"Expected {expected_count} edges, got {actual_count}"
        )

    def test_truss_numbers_correct(self, reference_data):
        expected = reference_data['expected_truss']

        actual = {}
        with open('/app/output/truss_decomposition.txt') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 3:
                    u, v, t = int(parts[0]), int(parts[1]), int(parts[2])
                    actual[(u, v)] = t

        errors = []
        for edge, truss in sorted(expected.items()):
            if edge not in actual:
                errors.append(f"Missing edge {edge}")
            elif actual[edge] != truss:
                errors.append(
                    f"Edge {edge}: expected truss {truss}, got {actual[edge]}"
                )

        for edge in sorted(actual.keys()):
            if edge not in expected:
                errors.append(f"Extra edge {edge} with truss {actual[edge]}")

        assert len(errors) == 0, (
            f"Truss decomposition errors ({len(errors)} total):\n"
            + "\n".join(errors[:20])
        )

    def test_truss_minimum_is_two(self):
        """All truss numbers must be >= 2."""
        with open('/app/output/truss_decomposition.txt') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 3:
                    t = int(parts[2])
                    assert t >= 2, (
                        f"Truss number {t} < 2 for edge ({parts[0]}, {parts[1]})"
                    )

    def test_sorted_by_edge(self):
        edges = []
        with open('/app/output/truss_decomposition.txt') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 3:
                    edges.append((int(parts[0]), int(parts[1])))
        assert edges == sorted(edges), "Truss output must be sorted by (u, v)"

    def test_u_less_than_v(self):
        with open('/app/output/truss_decomposition.txt') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 3:
                    u, v = int(parts[0]), int(parts[1])
                    assert u < v, f"Edge ({u}, {v}) violates u < v"
