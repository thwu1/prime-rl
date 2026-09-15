
"""
Verification of relational query engine outputs.
Rebuilds the project, runs each binary, and compares results against
independently-computed Python reference implementations.
"""
import os
import subprocess
import pytest


def load_edge_pairs(path):
    """Load (src, dst) pairs from a file."""
    pairs = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                pairs.append((int(parts[0]), int(parts[1])))
    return pairs


def load_node_list(path):
    """Load node IDs from a file, one per line."""
    nodes = []
    with open(path) as f:
        for line in f:
            s = line.strip()
            if s:
                nodes.append(int(s))
    return nodes


def compute_transitive_closure(edges):
    """Compute TC via iterative fixpoint, return count of reachable pairs."""
    all_nodes = set()
    adj = {}
    for a, b in edges:
        adj.setdefault(a, set()).add(b)
        all_nodes.add(a)
        all_nodes.add(b)

    reach = {n: set() for n in all_nodes}
    for a, b in edges:
        reach[a].add(b)

    changed = True
    while changed:
        changed = False
        for x in all_nodes:
            new_reach = set()
            for y in list(reach[x]):
                for z in reach.get(y, set()):
                    if z not in reach[x]:
                        new_reach.add(z)
            if new_reach:
                reach[x] |= new_reach
                changed = True

    return sum(len(s) for s in reach.values())


def count_directed_triangles(edges):
    """Count ordered triples (a,b,c) where a->b, b->c, a->c all exist."""
    edge_set = set(edges)
    adj = {}
    for a, b in edges:
        adj.setdefault(a, set()).add(b)

    count = 0
    for a in adj:
        for b in adj[a]:
            if b in adj:
                for c in adj[b]:
                    if (a, c) in edge_set:
                        count += 1
    return count


def compute_reaching_defs(cfg_edges, gen_pairs, kill_pairs, block_nodes):
    """
    Compute reaching definitions:
        rd(x, d) :- gen(x, d).
        rd(y, d) :- rd(x, d), !block(x), cfg(x, y), !kill(y, d).
    Returns count of unique (node, def) pairs.
    """
    adj = {}
    for a, b in cfg_edges:
        adj.setdefault(a, set()).add(b)

    kill_set = set(kill_pairs)
    block_set = set(block_nodes)
    rd = set(gen_pairs)

    changed = True
    while changed:
        changed = False
        new_rd = set()
        for (x, d) in rd:
            if x in block_set:
                continue
            for y in adj.get(x, set()):
                if (y, d) not in kill_set and (y, d) not in rd:
                    new_rd.add((y, d))
        if new_rd:
            rd |= new_rd
            changed = True

    return len(rd)


def compute_sccs(edges):
    """Compute SCCs via Kosaraju's algorithm, return (count, largest_size)."""
    all_nodes = set()
    adj = {}
    rev_adj = {}
    for a, b in edges:
        all_nodes.add(a)
        all_nodes.add(b)
        adj.setdefault(a, []).append(b)
        rev_adj.setdefault(b, []).append(a)

    # Phase 1: iterative DFS on original graph, record finish order
    visited = set()
    finish_order = []

    for start in sorted(all_nodes):
        if start in visited:
            continue
        stack = [(start, False)]
        while stack:
            n, processed = stack.pop()
            if processed:
                finish_order.append(n)
                continue
            if n in visited:
                continue
            visited.add(n)
            stack.append((n, True))
            for neighbor in adj.get(n, []):
                if neighbor not in visited:
                    stack.append((neighbor, False))

    # Phase 2: iterative DFS on reversed graph in reverse finish order
    visited2 = set()
    scc_sizes = []

    for start in reversed(finish_order):
        if start in visited2:
            continue
        count = 0
        stack = [start]
        while stack:
            n = stack.pop()
            if n in visited2:
                continue
            visited2.add(n)
            count += 1
            for neighbor in rev_adj.get(n, []):
                if neighbor not in visited2:
                    stack.append(neighbor)
        scc_sizes.append(count)

    return len(scc_sizes), max(scc_sizes) if scc_sizes else 0


def read_output(path):
    """Read a single integer from an output file."""
    with open(path) as f:
        return int(f.read().strip())


def get_cargo_env():
    """Return an env dict with cargo on PATH."""
    env = os.environ.copy()
    env["PATH"] = "/usr/local/cargo/bin:/root/.cargo/bin:" + env.get("PATH", "")
    return env


class TestBuild:
    """Verify the project compiles."""

    def test_cargo_builds(self):
        env = get_cargo_env()
        result = subprocess.run(
            ["cargo", "build", "--release"],
            cwd="/app",
            capture_output=True, text=True, timeout=300,
            env=env,
        )
        assert result.returncode == 0, \
            f"cargo build failed:\n{result.stderr}"


class TestTransitiveClosure:
    def test_correctness(self):
        if os.path.exists("/app/output/tc_count.txt"):
            os.remove("/app/output/tc_count.txt")
        env = get_cargo_env()
        result = subprocess.run(
            ["/app/target/release/transitive_closure"],
            cwd="/app",
            capture_output=True, text=True, timeout=60,
            env=env,
        )
        assert result.returncode == 0, \
            f"transitive_closure failed:\n{result.stderr}"
        edges = load_edge_pairs("/app/data/edges.txt")
        expected = compute_transitive_closure(edges)
        actual = read_output("/app/output/tc_count.txt")
        assert actual == expected, \
            f"TC count mismatch: expected {expected}, got {actual}"


class TestTriangles:
    def test_correctness(self):
        if os.path.exists("/app/output/tri_count.txt"):
            os.remove("/app/output/tri_count.txt")
        env = get_cargo_env()
        result = subprocess.run(
            ["/app/target/release/triangles"],
            cwd="/app",
            capture_output=True, text=True, timeout=60,
            env=env,
        )
        assert result.returncode == 0, \
            f"triangles failed:\n{result.stderr}"
        edges = load_edge_pairs("/app/data/edges.txt")
        expected = count_directed_triangles(edges)
        actual = read_output("/app/output/tri_count.txt")
        assert actual == expected, \
            f"Triangle count mismatch: expected {expected}, got {actual}"


class TestReachingDefs:
    def test_correctness(self):
        if os.path.exists("/app/output/rd_count.txt"):
            os.remove("/app/output/rd_count.txt")
        env = get_cargo_env()
        result = subprocess.run(
            ["/app/target/release/reaching_defs"],
            cwd="/app",
            capture_output=True, text=True, timeout=60,
            env=env,
        )
        assert result.returncode == 0, \
            f"reaching_defs failed:\n{result.stderr}"
        cfg = load_edge_pairs("/app/data/cfg.txt")
        gen = load_edge_pairs("/app/data/gen.txt")
        kill = load_edge_pairs("/app/data/kill.txt")
        block = load_node_list("/app/data/block.txt")
        expected = compute_reaching_defs(cfg, gen, kill, block)
        actual = read_output("/app/output/rd_count.txt")
        assert actual == expected, \
            f"Reaching defs count mismatch: expected {expected}, got {actual}"


class TestSCC:
    def test_correctness(self):
        if os.path.exists("/app/output/scc_count.txt"):
            os.remove("/app/output/scc_count.txt")
        if os.path.exists("/app/output/largest_scc.txt"):
            os.remove("/app/output/largest_scc.txt")
        env = get_cargo_env()
        result = subprocess.run(
            ["/app/target/release/scc"],
            cwd="/app",
            capture_output=True, text=True, timeout=60,
            env=env,
        )
        assert result.returncode == 0, \
            f"scc failed:\n{result.stderr}"
        edges = load_edge_pairs("/app/data/edges.txt")
        expected_count, expected_largest = compute_sccs(edges)
        actual_count = read_output("/app/output/scc_count.txt")
        actual_largest = read_output("/app/output/largest_scc.txt")
        assert actual_count == expected_count, \
            f"SCC count mismatch: expected {expected_count}, got {actual_count}"
        assert actual_largest == expected_largest, \
            f"Largest SCC mismatch: expected {expected_largest}, got {actual_largest}"


class TestEngineStructure:
    """Verify the engine was built as a Rust library with expected constructs."""

    def test_lib_exists(self):
        assert os.path.isfile("/app/src/lib.rs"), \
            "Engine library /app/src/lib.rs not found"

    def test_lib_has_key_types(self):
        with open("/app/src/lib.rs") as f:
            src = f.read()
        for name in ["Relation", "Variable", "join_into", "leapjoin_into"]:
            assert name in src, \
                f"Engine library missing expected construct: {name}"

    def test_binaries_use_engine(self):
        for binary in ["transitive_closure", "triangles", "reaching_defs", "scc"]:
            with open(f"/app/src/bin/{binary}.rs") as f:
                src = f.read()
            assert "datafrog_engine" in src, \
                f"{binary} does not import the engine library"
