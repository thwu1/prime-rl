
import subprocess
import random
import os
from collections import defaultdict, deque

import pytest


# ---------------------------------------------------------------------------
# Brute-force reference solver (BFS-based, O(N) per path operation)
# ---------------------------------------------------------------------------

class BruteForce:
    """Naive dynamic forest supporting the same operations as the LCT program."""

    def __init__(self, n, weights):
        self.n = n
        self.w = list(weights)          # 0-indexed
        self.adj = defaultdict(set)

    def link(self, u, v):
        self.adj[u].add(v)
        self.adj[v].add(u)

    def cut(self, u, v):
        self.adj[u].discard(v)
        self.adj[v].discard(u)

    def _find_path(self, u, v):
        if u == v:
            return [u]
        visited = {u}
        queue = deque([(u, [u])])
        while queue:
            node, path = queue.popleft()
            for nb in self.adj[node]:
                if nb not in visited:
                    visited.add(nb)
                    new_path = path + [nb]
                    if nb == v:
                        return new_path
                    queue.append((nb, new_path))
        return None

    def path_sum(self, u, v):
        p = self._find_path(u, v)
        return sum(self.w[x - 1] for x in p)

    def path_max(self, u, v):
        p = self._find_path(u, v)
        return max(self.w[x - 1] for x in p)

    def path_min(self, u, v):
        p = self._find_path(u, v)
        return min(self.w[x - 1] for x in p)

    def path_add(self, u, v, d):
        p = self._find_path(u, v)
        for x in p:
            self.w[x - 1] += d

    def update(self, u, val):
        self.w[u - 1] = val


# ---------------------------------------------------------------------------
# Random test-case generator
# ---------------------------------------------------------------------------

def generate_test_case(n, q, seed):
    """Return (input_text, expected_output_text) for a random test."""
    rng = random.Random(seed)
    weights = [rng.randint(-100, 100) for _ in range(n)]
    forest = BruteForce(n, list(weights))

    parent = list(range(n + 1))
    rank = [0] * (n + 1)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def unite(a, b):
        a, b = find(a), find(b)
        if a == b:
            return
        if rank[a] < rank[b]:
            a, b = b, a
        parent[b] = a
        if rank[a] == rank[b]:
            rank[a] += 1

    def rebuild_uf():
        nonlocal parent, rank
        parent[:] = list(range(n + 1))
        rank[:] = [0] * (n + 1)
        for eu, ev in edges:
            unite(eu, ev)

    edges = []
    adj = defaultdict(set)
    ops = []
    expected = []

    def connected_pair():
        if not edges:
            return None
        u0 = edges[rng.randint(0, len(edges) - 1)][0]
        visited = set()
        queue_bfs = deque([u0])
        visited.add(u0)
        component = [u0]
        while queue_bfs:
            nd = queue_bfs.popleft()
            for nb in adj[nd]:
                if nb not in visited:
                    visited.add(nb)
                    queue_bfs.append(nb)
                    component.append(nb)
        if len(component) < 2:
            return None
        a = rng.choice(component)
        b = rng.choice(component)
        while b == a:
            b = rng.choice(component)
        return a, b

    for _ in range(q):
        r = rng.random()

        if r < 0.18 and len(edges) < n - 1:
            found = False
            for _ in range(50):
                u = rng.randint(1, n)
                v = rng.randint(1, n)
                if u != v and find(u) != find(v):
                    unite(u, v)
                    forest.link(u, v)
                    edges.append((u, v))
                    adj[u].add(v)
                    adj[v].add(u)
                    ops.append(f"link {u} {v}")
                    found = True
                    break
            if not found:
                pair = connected_pair()
                if pair:
                    a, b = pair
                    expected.append(str(forest.path_sum(a, b)))
                    ops.append(f"path_sum {a} {b}")

        elif r < 0.26 and len(edges) > 2:
            idx = rng.randint(0, len(edges) - 1)
            u, v = edges.pop(idx)
            forest.cut(u, v)
            adj[u].discard(v)
            adj[v].discard(u)
            ops.append(f"cut {u} {v}")
            rebuild_uf()

        elif r < 0.42:
            pair = connected_pair()
            if pair:
                a, b = pair
                choice = rng.random()
                if choice < 0.33:
                    expected.append(str(forest.path_sum(a, b)))
                    ops.append(f"path_sum {a} {b}")
                elif choice < 0.66:
                    expected.append(str(forest.path_max(a, b)))
                    ops.append(f"path_max {a} {b}")
                else:
                    expected.append(str(forest.path_min(a, b)))
                    ops.append(f"path_min {a} {b}")

        elif r < 0.58:
            pair = connected_pair()
            if pair:
                a, b = pair
                d = rng.randint(-50, 50)
                forest.path_add(a, b, d)
                ops.append(f"add {a} {b} {d}")

        elif r < 0.72:
            u = rng.randint(1, n)
            w = rng.randint(-100, 100)
            forest.update(u, w)
            ops.append(f"update {u} {w}")

        else:
            pair = connected_pair()
            if pair:
                a, b = pair
                choice = rng.random()
                if choice < 0.5:
                    expected.append(str(forest.path_sum(a, b)))
                    ops.append(f"path_sum {a} {b}")
                else:
                    expected.append(str(forest.path_min(a, b)))
                    ops.append(f"path_min {a} {b}")

    input_text = f"{n}\n{' '.join(map(str, weights))}\n{len(ops)}\n"
    input_text += "\n".join(ops) + "\n"
    expected_text = "\n".join(expected) + ("\n" if expected else "")
    return input_text, expected_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_binary(binary_path, input_text, timeout=30):
    proc = subprocess.run(
        [binary_path],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.stdout, proc.returncode, proc.stderr


@pytest.fixture(scope="session")
def binary():
    result = subprocess.run(
        ["cargo", "build", "--release"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Compilation failed:\n{result.stderr}\n{result.stdout}"
    )
    path = "/app/target/release/forest_query"
    assert os.path.exists(path), "Binary not found after compilation"
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_compiles(binary):
    """The project must compile without errors."""
    assert os.path.exists(binary)


def test_sample1(binary):
    """Sample test 1: link, path_sum, path_max, path_min, update."""
    with open("/app/data/sample1.in") as f:
        inp = f.read()
    with open("/app/data/sample1.out") as f:
        expected = f.read().strip()
    actual, rc, stderr = run_binary(binary, inp)
    assert rc == 0, f"Program exited with code {rc}\nstderr: {stderr}"
    assert actual.strip() == expected, (
        f"Wrong output on sample1.\nExpected:\n{expected}\nActual:\n{actual.strip()}"
    )


def test_sample2(binary):
    """Sample test 2: link, add, cut, update, path_min interactions."""
    with open("/app/data/sample2.in") as f:
        inp = f.read()
    with open("/app/data/sample2.out") as f:
        expected = f.read().strip()
    actual, rc, stderr = run_binary(binary, inp)
    assert rc == 0, f"Program exited with code {rc}\nstderr: {stderr}"
    assert actual.strip() == expected, (
        f"Wrong output on sample2.\nExpected:\n{expected}\nActual:\n{actual.strip()}"
    )


def test_stress_small(binary):
    """Randomly generated stress test: N=30, Q=150."""
    inp, expected = generate_test_case(30, 150, seed=171717)
    actual, rc, stderr = run_binary(binary, inp)
    assert rc == 0, f"Crash on small stress test\nstderr: {stderr}"
    assert actual.strip() == expected.strip(), (
        "Wrong output on small stress test.\n"
        f"Expected (first 500 chars):\n{expected[:500]}\n"
        f"Actual   (first 500 chars):\n{actual[:500]}"
    )


def test_stress_with_cuts(binary):
    """Stress test heavy on cuts and re-links: N=50, Q=300."""
    inp, expected = generate_test_case(50, 300, seed=282828)
    actual, rc, stderr = run_binary(binary, inp)
    assert rc == 0, f"Crash on cut-heavy stress test\nstderr: {stderr}"
    assert actual.strip() == expected.strip(), (
        "Wrong output on cut-heavy stress test.\n"
        f"Expected (first 500 chars):\n{expected[:500]}\n"
        f"Actual   (first 500 chars):\n{actual[:500]}"
    )


def test_stress_medium(binary):
    """Medium stress test: N=200, Q=1000."""
    inp, expected = generate_test_case(200, 1000, seed=393939)
    actual, rc, stderr = run_binary(binary, inp)
    assert rc == 0, f"Crash on medium stress test\nstderr: {stderr}"
    assert actual.strip() == expected.strip(), (
        "Wrong output on medium stress test.\n"
        f"Expected (first 500 chars):\n{expected[:500]}\n"
        f"Actual   (first 500 chars):\n{actual[:500]}"
    )


def test_stress_large(binary):
    """Larger stress test: N=500, Q=3000."""
    inp, expected = generate_test_case(500, 3000, seed=505050)
    actual, rc, stderr = run_binary(binary, inp, timeout=60)
    assert rc == 0, f"Crash on large stress test\nstderr: {stderr}"
    assert actual.strip() == expected.strip(), (
        "Wrong output on large stress test.\n"
        f"Expected (first 500 chars):\n{expected[:500]}\n"
        f"Actual   (first 500 chars):\n{actual[:500]}"
    )


def test_add_then_minmax(binary):
    """Targeted test: add operation followed by path_min and path_max queries."""
    inp = (
        "4\n"
        "10 -5 20 3\n"
        "12\n"
        "link 1 2\n"
        "link 2 3\n"
        "link 3 4\n"
        "path_min 1 4\n"
        "path_max 1 4\n"
        "add 1 4 7\n"
        "path_min 1 4\n"
        "path_max 1 4\n"
        "path_sum 1 4\n"
        "update 2 50\n"
        "path_min 1 4\n"
        "path_max 1 4\n"
    )
    # Initial: [10, -5, 20, 3]
    # path_min 1 4: min(10,-5,20,3) = -5
    # path_max 1 4: max(10,-5,20,3) = 20
    # add 1 4 7: [17, 2, 27, 10]
    # path_min 1 4: min(17,2,27,10) = 2
    # path_max 1 4: max(17,2,27,10) = 27
    # path_sum 1 4: 17+2+27+10 = 56
    # update 2 50: [17, 50, 27, 10]
    # path_min 1 4: min(17,50,27,10) = 10
    # path_max 1 4: max(17,50,27,10) = 50
    expected = "-5\n20\n2\n27\n56\n10\n50"
    actual, rc, stderr = run_binary(binary, inp)
    assert rc == 0, f"Program exited with code {rc}\nstderr: {stderr}"
    assert actual.strip() == expected, (
        f"Wrong output on add_then_minmax test.\n"
        f"Expected:\n{expected}\nActual:\n{actual.strip()}"
    )


def test_cut_relink_integrity(binary):
    """Targeted test: cut and re-link to verify fa pointer cleanup."""
    inp = (
        "5\n"
        "1 2 3 4 5\n"
        "14\n"
        "link 1 2\n"
        "link 2 3\n"
        "link 3 4\n"
        "link 4 5\n"
        "path_sum 1 5\n"
        "cut 3 4\n"
        "path_sum 1 3\n"
        "path_sum 4 5\n"
        "link 3 5\n"
        "path_sum 1 5\n"
        "path_min 1 5\n"
        "path_max 1 5\n"
        "add 2 4 100\n"
        "path_sum 1 5\n"
    )
    # Initial: [1,2,3,4,5], tree 1-2-3-4-5
    # path_sum 1 5: 1+2+3+4+5 = 15
    # cut 3 4: trees {1-2-3} and {4-5}
    # path_sum 1 3: 1+2+3 = 6
    # path_sum 4 5: 4+5 = 9
    # link 3 5: tree 1-2-3-5-4
    # path_sum 1 5: 1+2+3+5 = 11  (path 1->2->3->5)
    # Wait, path 1 to 5 goes 1-2-3-5, so sum=1+2+3+5=11
    # path_min 1 5: min(1,2,3,5) = 1
    # path_max 1 5: max(1,2,3,5) = 5
    # add 2 4: path 2->3->5->4, add 100 to each: w=[1, 102, 103, 104, 105]
    # path_sum 1 5: path 1->2->3->5: 1+102+103+105 = 311
    expected = "15\n6\n9\n11\n1\n5\n311"
    actual, rc, stderr = run_binary(binary, inp)
    assert rc == 0, f"Program exited with code {rc}\nstderr: {stderr}"
    assert actual.strip() == expected, (
        f"Wrong output on cut_relink_integrity test.\n"
        f"Expected:\n{expected}\nActual:\n{actual.strip()}"
    )
