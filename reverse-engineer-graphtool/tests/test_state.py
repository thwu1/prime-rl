"""
Tests for graphtool reimplementation.

Compares the agent's Python implementation at /app/graphtool.py against
the reference binary /app/ref_tool across diverse graph inputs and all commands,
including binary serialization format, PageRank, and strongly connected components.

"""

import os
import subprocess
import tempfile
import pytest

REF = "/app/ref_tool"
IMPL = "/app/graphtool.py"


def run_ref(graph, args):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".grph", delete=False) as f:
        f.write(graph)
        tmp = f.name
    try:
        cmd = [REF, args[0], tmp] + args[1:]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return r.stdout, r.stderr, r.returncode
    finally:
        os.unlink(tmp)


def run_impl(graph, args):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".grph", delete=False) as f:
        f.write(graph)
        tmp = f.name
    try:
        cmd = ["python3", IMPL, args[0], tmp] + args[1:]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return r.stdout, r.stderr, r.returncode
    finally:
        os.unlink(tmp)


def run_ref_raw(graph, args):
    """Run ref tool, return raw bytes stdout (for binary output)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".grph", delete=False) as f:
        f.write(graph)
        tmp = f.name
    try:
        cmd = [REF, args[0], tmp] + args[1:]
        r = subprocess.run(cmd, capture_output=True, timeout=15)
        return r.stdout, r.stderr, r.returncode
    finally:
        os.unlink(tmp)


def run_impl_raw(graph, args):
    """Run impl tool, return raw bytes stdout (for binary output)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".grph", delete=False) as f:
        f.write(graph)
        tmp = f.name
    try:
        cmd = ["python3", IMPL, args[0], tmp] + args[1:]
        r = subprocess.run(cmd, capture_output=True, timeout=15)
        return r.stdout, r.stderr, r.returncode
    finally:
        os.unlink(tmp)


def assert_match(graph, args):
    """Assert agent implementation matches reference on stdout and exit code."""
    ref_out, ref_err, ref_rc = run_ref(graph, args)
    imp_out, imp_err, imp_rc = run_impl(graph, args)
    assert imp_out == ref_out, (
        f"stdout mismatch for args={args}\n"
        f"--- expected ---\n{ref_out}\n--- got ---\n{imp_out}"
    )
    assert imp_rc == ref_rc, (
        f"exit code mismatch for args={args}: expected {ref_rc}, got {imp_rc}"
    )
    assert bool(imp_err) == bool(ref_err), (
        f"stderr presence mismatch for args={args}: "
        f"ref_err={'(has)' if ref_err else '(empty)'}, "
        f"imp_err={'(has)' if imp_err else '(empty)'}"
    )


def assert_match_bytes(graph, args):
    """Assert binary output matches byte-for-byte."""
    ref_out, ref_err, ref_rc = run_ref_raw(graph, args)
    imp_out, imp_err, imp_rc = run_impl_raw(graph, args)
    assert imp_out == ref_out, (
        f"binary output mismatch for args={args}\n"
        f"ref len={len(ref_out)}, imp len={len(imp_out)}"
    )
    assert imp_rc == ref_rc, (
        f"exit code mismatch for args={args}: expected {ref_rc}, got {imp_rc}"
    )


# ---- Graphs ----

SIMPLE_DAG = """\
node A
node B
node C
node D
edge A -> B
edge A -> C
edge B -> D
edge C -> D
"""

WEIGHTED = """\
@weighted
node A
node B
node C
node D
edge A -> B 1.0
edge A -> C 4.0
edge B -> C 2.0
edge B -> D 6.0
edge C -> D 1.0
"""

CYCLIC = """\
node A
node B
node C
edge A -> B
edge B -> C
edge C -> A
"""

SELF_LOOP_DUP = """\
node A
node B
edge A -> B
edge A -> B
edge A -> A
edge B -> A
"""

DISCONNECTED = """\
node A
node B
node C
node D
edge A -> B
edge C -> D
"""

EMPTY = """\
# empty graph
"""

SINGLE_NODE = """\
node Z
"""

COMPLEX_WEIGHTED = """\
@weighted
edge A -> B 1.0
edge A -> C 5.0
edge B -> C 2.0
edge B -> D 4.0
edge C -> D 1.0
edge C -> E 3.0
edge D -> E 2.0
edge D -> F 5.0
edge E -> F 1.0
"""

WEIGHTED_DEFAULT = """\
@weighted
edge X -> Y
edge Y -> Z
"""

DIAMOND_WEIGHTED = """\
@weighted
edge S -> A 2.0
edge S -> B 3.0
edge A -> T 5.0
edge B -> T 1.0
"""

LONG_CHAIN = """\
edge a -> b
edge b -> c
edge c -> d
edge d -> e
edge e -> f
edge f -> g
"""

IMPLICIT_NODES = """\
edge X -> Y
edge Y -> Z
"""

DUP_WEIGHTED = """\
@weighted
edge A -> B 3.0
edge A -> B 1.0
edge B -> C 1.0
"""

MULTI_SCC = """\
edge A -> B
edge B -> A
edge C -> D
edge D -> C
edge A -> C
edge D -> E
"""

LARGE_SCC = """\
edge A -> B
edge B -> C
edge C -> D
edge D -> E
edge E -> A
edge B -> D
edge D -> B
"""

PAGERANK_STAR = """\
edge B -> A
edge C -> A
edge D -> A
edge E -> A
"""

PAGERANK_LOOP_DANGLE = """\
edge A -> B
edge B -> C
edge C -> A
edge A -> D
"""


# ---- Anti-cheat ----

class TestAntiCheat:
    def test_implementation_exists(self):
        assert os.path.exists(IMPL), f"{IMPL} does not exist"

    def test_is_python(self):
        with open(IMPL) as f:
            src = f.read()
        assert len(src) > 50, "Implementation is too small to be genuine"

    def test_no_ref_delegation(self):
        with open(IMPL) as f:
            src = f.read().lower()
        assert "ref_tool" not in src, "Implementation must not call ref_tool"
        assert "/app/ref" not in src, "Implementation must not reference ref binary"

    def test_has_binary_format_code(self):
        """Implementation must handle binary serialization natively."""
        with open(IMPL) as f:
            src = f.read().lower()
        assert "struct" in src or "pack" in src or "bytearray" in src, (
            "Implementation must contain binary serialization code"
        )


# ---- Info command ----

class TestInfo:
    def test_simple_dag(self):
        assert_match(SIMPLE_DAG, ["info"])

    def test_weighted(self):
        assert_match(WEIGHTED, ["info"])

    def test_cyclic(self):
        assert_match(CYCLIC, ["info"])

    def test_self_loop_dup(self):
        assert_match(SELF_LOOP_DUP, ["info"])

    def test_disconnected(self):
        assert_match(DISCONNECTED, ["info"])

    def test_empty(self):
        assert_match(EMPTY, ["info"])

    def test_single_node(self):
        assert_match(SINGLE_NODE, ["info"])

    def test_complex_weighted(self):
        assert_match(COMPLEX_WEIGHTED, ["info"])

    def test_implicit_nodes(self):
        assert_match(IMPLICIT_NODES, ["info"])

    def test_weighted_default_weight(self):
        assert_match(WEIGHTED_DEFAULT, ["info"])


# ---- Adj command ----

class TestAdj:
    def test_simple_dag(self):
        assert_match(SIMPLE_DAG, ["adj"])

    def test_weighted(self):
        assert_match(WEIGHTED, ["adj"])

    def test_self_loop_dup(self):
        assert_match(SELF_LOOP_DUP, ["adj"])

    def test_disconnected(self):
        assert_match(DISCONNECTED, ["adj"])

    def test_empty(self):
        assert_match(EMPTY, ["adj"])

    def test_single_node(self):
        assert_match(SINGLE_NODE, ["adj"])

    def test_complex_weighted(self):
        assert_match(COMPLEX_WEIGHTED, ["adj"])

    def test_weighted_default(self):
        assert_match(WEIGHTED_DEFAULT, ["adj"])


# ---- Shortest command ----

class TestShortest:
    def test_simple_reachable(self):
        assert_match(SIMPLE_DAG, ["shortest", "A", "D"])

    def test_simple_direct(self):
        assert_match(SIMPLE_DAG, ["shortest", "A", "C"])

    def test_weighted_shortest(self):
        assert_match(WEIGHTED, ["shortest", "A", "D"])

    def test_weighted_direct(self):
        assert_match(WEIGHTED, ["shortest", "A", "C"])

    def test_no_path(self):
        assert_match(DISCONNECTED, ["shortest", "A", "D"])

    def test_same_node(self):
        assert_match(SIMPLE_DAG, ["shortest", "A", "A"])

    def test_same_node_weighted(self):
        assert_match(WEIGHTED, ["shortest", "A", "A"])

    def test_node_not_found(self):
        assert_match(SINGLE_NODE, ["shortest", "Z", "Q"])

    def test_complex_weighted(self):
        assert_match(COMPLEX_WEIGHTED, ["shortest", "A", "F"])

    def test_diamond_weighted(self):
        assert_match(DIAMOND_WEIGHTED, ["shortest", "S", "T"])

    def test_long_chain(self):
        assert_match(LONG_CHAIN, ["shortest", "a", "g"])

    def test_reverse_unreachable(self):
        assert_match(SIMPLE_DAG, ["shortest", "D", "A"])

    def test_dup_weighted_shortest(self):
        assert_match(DUP_WEIGHTED, ["shortest", "A", "C"])


# ---- Topo command ----

class TestTopo:
    def test_simple_dag(self):
        assert_match(SIMPLE_DAG, ["topo"])

    def test_cycle_error(self):
        assert_match(CYCLIC, ["topo"])

    def test_self_loop_cycle(self):
        assert_match(SELF_LOOP_DUP, ["topo"])

    def test_disconnected(self):
        assert_match(DISCONNECTED, ["topo"])

    def test_empty(self):
        assert_match(EMPTY, ["topo"])

    def test_single_node(self):
        assert_match(SINGLE_NODE, ["topo"])

    def test_complex_weighted(self):
        assert_match(COMPLEX_WEIGHTED, ["topo"])

    def test_long_chain(self):
        assert_match(LONG_CHAIN, ["topo"])

    def test_tie_breaking(self):
        graph = "node D\nnode C\nnode B\nnode A\nedge A -> C\nedge B -> D\n"
        assert_match(graph, ["topo"])


# ---- Allpaths command ----

class TestAllPaths:
    def test_simple_two_paths(self):
        assert_match(SIMPLE_DAG, ["allpaths", "A", "D"])

    def test_simple_direct_and_indirect(self):
        graph = "edge A -> B\nedge B -> C\nedge A -> C\n"
        assert_match(graph, ["allpaths", "A", "C"])

    def test_weighted_multiple(self):
        assert_match(WEIGHTED, ["allpaths", "A", "D"])

    def test_no_paths(self):
        assert_match(DISCONNECTED, ["allpaths", "A", "D"])

    def test_complex_weighted_allpaths(self):
        assert_match(COMPLEX_WEIGHTED, ["allpaths", "A", "F"])

    def test_node_not_found(self):
        assert_match(SINGLE_NODE, ["allpaths", "Z", "Q"])

    def test_same_node(self):
        assert_match(SIMPLE_DAG, ["allpaths", "A", "A"])

    def test_cyclic_allpaths(self):
        assert_match(CYCLIC, ["allpaths", "A", "C"])

    def test_diamond_weighted(self):
        assert_match(DIAMOND_WEIGHTED, ["allpaths", "S", "T"])

    def test_long_chain_allpaths(self):
        assert_match(LONG_CHAIN, ["allpaths", "a", "g"])

    def test_reverse_no_paths(self):
        assert_match(SIMPLE_DAG, ["allpaths", "D", "A"])

    def test_dup_weighted_allpaths(self):
        assert_match(DUP_WEIGHTED, ["allpaths", "A", "C"])

    def test_many_paths(self):
        graph = """\
edge A -> B
edge A -> C
edge A -> D
edge B -> C
edge B -> D
edge C -> D
"""
        assert_match(graph, ["allpaths", "A", "D"])


# ---- Serialize command (binary format) ----

class TestSerialize:
    def test_simple_dag(self):
        assert_match_bytes(SIMPLE_DAG, ["serialize"])

    def test_weighted(self):
        assert_match_bytes(WEIGHTED, ["serialize"])

    def test_empty(self):
        assert_match_bytes(EMPTY, ["serialize"])

    def test_single_node(self):
        assert_match_bytes(SINGLE_NODE, ["serialize"])

    def test_complex_weighted(self):
        assert_match_bytes(COMPLEX_WEIGHTED, ["serialize"])

    def test_self_loop_dup(self):
        assert_match_bytes(SELF_LOOP_DUP, ["serialize"])

    def test_disconnected(self):
        assert_match_bytes(DISCONNECTED, ["serialize"])

    def test_implicit_nodes(self):
        assert_match_bytes(IMPLICIT_NODES, ["serialize"])

    def test_weighted_default(self):
        assert_match_bytes(WEIGHTED_DEFAULT, ["serialize"])

    def test_dup_weighted(self):
        assert_match_bytes(DUP_WEIGHTED, ["serialize"])

    def test_cyclic(self):
        assert_match_bytes(CYCLIC, ["serialize"])

    def test_binary_has_magic(self):
        """Verify the binary output starts with the correct magic bytes."""
        ref_out, _, rc = run_ref_raw(SIMPLE_DAG, ["serialize"])
        assert rc == 0
        assert ref_out[:4] == b"GRB\x01", "Binary must start with magic bytes GRB\\x01"

    def test_binary_length_unweighted(self):
        """Verify binary size is consistent with the format spec."""
        ref_out, _, _ = run_ref_raw(SIMPLE_DAG, ["serialize"])
        imp_out, _, _ = run_impl_raw(SIMPLE_DAG, ["serialize"])
        assert len(ref_out) == len(imp_out), (
            f"Binary length mismatch: ref={len(ref_out)}, impl={len(imp_out)}"
        )

    def test_binary_length_weighted(self):
        """Weighted graphs should have larger binary output due to float64 weights."""
        ref_out, _, _ = run_ref_raw(WEIGHTED, ["serialize"])
        imp_out, _, _ = run_impl_raw(WEIGHTED, ["serialize"])
        assert len(ref_out) == len(imp_out)


# ---- Deserialize command (binary -> text) ----

class TestDeserialize:
    def _roundtrip(self, graph):
        """Serialize with ref, deserialize with impl, compare to ref deserialize."""
        ref_bin, _, rc = run_ref_raw(graph, ["serialize"])
        assert rc == 0, "Ref serialize failed"
        # Deserialize with ref
        with tempfile.NamedTemporaryFile(suffix=".grb", delete=False) as f:
            f.write(ref_bin)
            tmp = f.name
        try:
            ref_text = subprocess.run(
                [REF, "deserialize", tmp],
                capture_output=True, text=True, timeout=15
            )
            imp_text = subprocess.run(
                ["python3", IMPL, "deserialize", tmp],
                capture_output=True, text=True, timeout=15
            )
            assert imp_text.stdout == ref_text.stdout, (
                f"Deserialize mismatch\n"
                f"--- ref ---\n{ref_text.stdout}\n--- impl ---\n{imp_text.stdout}"
            )
            assert imp_text.returncode == ref_text.returncode
        finally:
            os.unlink(tmp)

    def _cross_roundtrip(self, graph):
        """Serialize with impl, deserialize with ref to test format compat."""
        imp_bin, _, rc = run_impl_raw(graph, ["serialize"])
        assert rc == 0, "Impl serialize failed"
        with tempfile.NamedTemporaryFile(suffix=".grb", delete=False) as f:
            f.write(imp_bin)
            tmp = f.name
        try:
            ref_text = subprocess.run(
                [REF, "deserialize", tmp],
                capture_output=True, text=True, timeout=15
            )
            assert ref_text.returncode == 0, (
                f"Ref failed to deserialize impl binary: {ref_text.stderr}"
            )
        finally:
            os.unlink(tmp)

    def test_simple_dag(self):
        self._roundtrip(SIMPLE_DAG)

    def test_weighted(self):
        self._roundtrip(WEIGHTED)

    def test_empty(self):
        self._roundtrip(EMPTY)

    def test_single_node(self):
        self._roundtrip(SINGLE_NODE)

    def test_complex_weighted(self):
        self._roundtrip(COMPLEX_WEIGHTED)

    def test_disconnected(self):
        self._roundtrip(DISCONNECTED)

    def test_cross_simple_dag(self):
        self._cross_roundtrip(SIMPLE_DAG)

    def test_cross_weighted(self):
        self._cross_roundtrip(WEIGHTED)

    def test_cross_complex(self):
        self._cross_roundtrip(COMPLEX_WEIGHTED)

    def test_invalid_crc(self):
        """Deserialize should fail on corrupted binary."""
        ref_bin, _, _ = run_ref_raw(SIMPLE_DAG, ["serialize"])
        corrupted = bytearray(ref_bin)
        if len(corrupted) > 10:
            corrupted[8] ^= 0xFF  # flip a byte in the payload
        with tempfile.NamedTemporaryFile(suffix=".grb", delete=False) as f:
            f.write(bytes(corrupted))
            tmp = f.name
        try:
            imp = subprocess.run(
                ["python3", IMPL, "deserialize", tmp],
                capture_output=True, text=True, timeout=15
            )
            assert imp.returncode != 0, "Should fail on corrupted binary"
        finally:
            os.unlink(tmp)


# ---- PageRank command ----

class TestPageRank:
    def test_simple_dag(self):
        assert_match(SIMPLE_DAG, ["pagerank"])

    def test_weighted(self):
        assert_match(WEIGHTED, ["pagerank"])

    def test_cyclic(self):
        assert_match(CYCLIC, ["pagerank"])

    def test_disconnected(self):
        assert_match(DISCONNECTED, ["pagerank"])

    def test_single_node(self):
        assert_match(SINGLE_NODE, ["pagerank"])

    def test_star_graph(self):
        assert_match(PAGERANK_STAR, ["pagerank"])

    def test_loop_with_dangling(self):
        assert_match(PAGERANK_LOOP_DANGLE, ["pagerank"])

    def test_complex_weighted(self):
        assert_match(COMPLEX_WEIGHTED, ["pagerank"])

    def test_self_loop_dup(self):
        assert_match(SELF_LOOP_DUP, ["pagerank"])

    def test_custom_damping(self):
        assert_match(SIMPLE_DAG, ["pagerank", "0.5"])

    def test_custom_damping_and_iter(self):
        assert_match(SIMPLE_DAG, ["pagerank", "0.9", "10"])

    def test_low_damping(self):
        assert_match(CYCLIC, ["pagerank", "0.1"])

    def test_high_damping(self):
        assert_match(COMPLEX_WEIGHTED, ["pagerank", "0.99"])

    def test_one_iteration(self):
        assert_match(SIMPLE_DAG, ["pagerank", "0.85", "1"])

    def test_long_chain(self):
        assert_match(LONG_CHAIN, ["pagerank"])

    def test_implicit_nodes(self):
        assert_match(IMPLICIT_NODES, ["pagerank"])


# ---- SCC (Strongly Connected Components) ----

class TestSCC:
    def test_simple_dag(self):
        """DAG: each node is its own SCC."""
        assert_match(SIMPLE_DAG, ["scc"])

    def test_single_cycle(self):
        """All nodes in one SCC."""
        assert_match(CYCLIC, ["scc"])

    def test_multi_scc(self):
        """Two separate SCCs plus a singleton."""
        assert_match(MULTI_SCC, ["scc"])

    def test_large_scc(self):
        """Single large SCC."""
        assert_match(LARGE_SCC, ["scc"])

    def test_self_loop_dup(self):
        assert_match(SELF_LOOP_DUP, ["scc"])

    def test_disconnected(self):
        assert_match(DISCONNECTED, ["scc"])

    def test_single_node(self):
        assert_match(SINGLE_NODE, ["scc"])

    def test_empty(self):
        assert_match(EMPTY, ["scc"])

    def test_complex_weighted(self):
        assert_match(COMPLEX_WEIGHTED, ["scc"])

    def test_long_chain(self):
        assert_match(LONG_CHAIN, ["scc"])

    def test_implicit_nodes(self):
        assert_match(IMPLICIT_NODES, ["scc"])

    def test_mutual_pairs(self):
        """Multiple mutual pairs."""
        graph = "edge A -> B\nedge B -> A\nedge C -> D\nedge D -> C\nedge E -> F\nedge F -> E\n"
        assert_match(graph, ["scc"])

    def test_nested_scc(self):
        """SCC within an SCC-like structure."""
        graph = """\
edge A -> B
edge B -> C
edge C -> A
edge C -> D
edge D -> E
edge E -> F
edge F -> D
"""
        assert_match(graph, ["scc"])
