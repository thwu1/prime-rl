
import json
import os
import subprocess
import tempfile
import time
from math import comb

import pytest


TOOL = "/app/quartet_tool.py"


def run_tool(input_content, expect_fail=False, timeout=120):
    """Write input to temp file, run tool, return parsed JSON or returncode."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".nwk", delete=False, dir="/tmp"
    ) as fin:
        fin.write(input_content)
        fin_path = fin.name
    out_path = fin_path + ".json"
    try:
        result = subprocess.run(
            ["python3", TOOL, fin_path, "-o", out_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if expect_fail:
            return result.returncode
        assert result.returncode == 0, (
            f"Tool failed (rc={result.returncode}): {result.stderr}"
        )
        with open(out_path) as f:
            return json.load(f)
    finally:
        if os.path.exists(fin_path):
            os.unlink(fin_path)
        if os.path.exists(out_path):
            os.unlink(out_path)


def get_pair(data, i, j):
    for p in data["pairwise"]:
        if p["i"] == i and p["j"] == j:
            return p
    raise ValueError(f"Pair ({i},{j}) not found in output")


# ---------------------------------------------------------------------------
# Tree generation helpers for large-tree tests
# ---------------------------------------------------------------------------
def make_pectinate(labels):
    """Generate a pectinate (caterpillar) Newick tree."""
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"({labels[0]},{labels[1]})"
    return f"({labels[0]},{make_pectinate(labels[1:])})"


def make_balanced(labels):
    """Generate a balanced Newick tree."""
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"({labels[0]},{labels[1]})"
    mid = len(labels) // 2
    return f"({make_balanced(labels[:mid])},{make_balanced(labels[mid:])})"


# ---------------------------------------------------------------------------
# C++ binary integration
# ---------------------------------------------------------------------------
class TestBinaryIntegration:

    def test_cpp_binary_compiled(self):
        """The C++ tqdist binary must be compiled and present."""
        assert os.path.isfile("/app/tqdist/tqdist"), \
            "C++ tqdist binary not found at /app/tqdist/tqdist"

    def test_cpp_binary_runs(self):
        """The binary should produce output for a test file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".nwk", delete=False, dir="/tmp"
        ) as f:
            f.write("((a,b),(c,d));\n((a,c),(b,d));\n")
            f_path = f.name
        try:
            result = subprocess.run(
                ["/app/tqdist/tqdist", f_path],
                capture_output=True, text=True, timeout=10,
            )
            assert result.returncode == 0, f"Binary failed: {result.stderr}"
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            # 2 trees => 3 lines: (0,0), (1,0), (1,1)
            assert len(lines) == 3
        finally:
            os.unlink(f_path)


# ---------------------------------------------------------------------------
# 4-leaf trees
# ---------------------------------------------------------------------------
class TestFourLeaf:

    def test_identical_binary(self):
        data = run_tool("((a,b),(c,d));\n((a,b),(c,d));\n")
        p = get_pair(data, 0, 1)
        assert p["Q"] == 1
        assert p["s"] == 1
        assert p["d"] == 0
        assert p["r1"] == 0
        assert p["r2"] == 0
        assert p["u"] == 0
        m = p["metrics"]
        assert m["do_not_conflict"] == 1.0
        assert m["explicitly_agree"] == 1.0
        assert m["strict_joint_assertions"] == 1.0
        assert m["semi_strict_joint_assertions"] == 1.0
        assert m["symmetric_difference"] == 1.0
        assert m["marczewski_steinhaus"] == 1.0
        assert m["steel_penny"] == 1.0
        assert m["quartet_divergence"] == 1.0

    def test_different_binary(self):
        data = run_tool("((a,b),(c,d));\n((a,c),(b,d));\n")
        p = get_pair(data, 0, 1)
        assert p["Q"] == 1
        assert p["s"] == 0
        assert p["d"] == 1
        assert p["r1"] == 0
        assert p["r2"] == 0
        assert p["u"] == 0
        m = p["metrics"]
        assert m["do_not_conflict"] == 0.0
        assert m["explicitly_agree"] == 0.0
        assert m["strict_joint_assertions"] == 0.0
        assert m["semi_strict_joint_assertions"] == 0.0
        assert m["symmetric_difference"] == 0.0
        assert m["marczewski_steinhaus"] == 0.0
        assert m["steel_penny"] == 0.0
        assert m["quartet_divergence"] == 0.0

    def test_binary_vs_star(self):
        data = run_tool("((a,b),(c,d));\n(a,b,c,d);\n")
        p = get_pair(data, 0, 1)
        assert p["Q"] == 1
        assert p["s"] == 0
        assert p["d"] == 0
        assert p["r1"] == 1
        assert p["r2"] == 0
        assert p["u"] == 0
        m = p["metrics"]
        assert m["do_not_conflict"] == 1.0
        assert m["explicitly_agree"] == 0.0
        assert m["strict_joint_assertions"] is None
        assert m["semi_strict_joint_assertions"] is None
        assert m["symmetric_difference"] == 0.0
        assert m["marczewski_steinhaus"] == 0.0
        assert m["steel_penny"] == 0.0
        assert m["quartet_divergence"] == 0.5

    def test_star_vs_star(self):
        data = run_tool("(a,b,c,d);\n(a,b,c,d);\n")
        p = get_pair(data, 0, 1)
        assert p["Q"] == 1
        assert p["s"] == 0
        assert p["d"] == 0
        assert p["r1"] == 0
        assert p["r2"] == 0
        assert p["u"] == 1
        m = p["metrics"]
        assert m["do_not_conflict"] == 1.0
        assert m["explicitly_agree"] == 0.0
        assert m["strict_joint_assertions"] is None
        assert m["semi_strict_joint_assertions"] == 0.0
        assert m["symmetric_difference"] is None
        assert m["marczewski_steinhaus"] is None
        assert m["steel_penny"] == 1.0
        assert m["quartet_divergence"] == 1.0

    def test_all_three_binary_disagree(self):
        """All three distinct binary 4-leaf trees are pairwise different."""
        data = run_tool(
            "((a,b),(c,d));\n((a,c),(b,d));\n((a,d),(b,c));\n"
        )
        assert len(data["pairwise"]) == 3
        for p in data["pairwise"]:
            assert p["Q"] == 1
            assert p["s"] == 0
            assert p["d"] == 1


# ---------------------------------------------------------------------------
# 5-leaf trees
# ---------------------------------------------------------------------------
class TestFiveLeaf:

    def test_two_binary(self):
        data = run_tool("((a,b),(c,(d,e)));\n((a,c),(b,(d,e)));\n")
        p = get_pair(data, 0, 1)
        assert p["Q"] == 5
        assert p["s"] == 3
        assert p["d"] == 2
        assert p["r1"] == 0
        assert p["r2"] == 0
        assert p["u"] == 0
        m = p["metrics"]
        assert abs(m["do_not_conflict"] - 0.6) < 1e-9
        assert abs(m["explicitly_agree"] - 0.6) < 1e-9
        assert abs(m["strict_joint_assertions"] - 0.6) < 1e-9
        assert abs(m["semi_strict_joint_assertions"] - 0.6) < 1e-9
        assert abs(m["symmetric_difference"] - 0.6) < 1e-9
        assert abs(m["marczewski_steinhaus"] - 3.0 / 7.0) < 1e-9
        assert abs(m["steel_penny"] - 0.6) < 1e-9
        assert abs(m["quartet_divergence"] - 0.6) < 1e-9

    def test_binary_vs_polytomy(self):
        data = run_tool("((a,b),(c,(d,e)));\n(a,b,c,(d,e));\n")
        p = get_pair(data, 0, 1)
        assert p["Q"] == 5
        assert p["s"] == 3
        assert p["d"] == 0
        assert p["r1"] == 2
        assert p["r2"] == 0
        assert p["u"] == 0
        m = p["metrics"]
        assert m["do_not_conflict"] == 1.0
        assert abs(m["explicitly_agree"] - 0.6) < 1e-9
        assert m["strict_joint_assertions"] == 1.0
        assert m["semi_strict_joint_assertions"] == 1.0
        assert abs(m["symmetric_difference"] - 0.75) < 1e-9
        assert abs(m["marczewski_steinhaus"] - 0.6) < 1e-9
        assert abs(m["steel_penny"] - 0.6) < 1e-9
        assert abs(m["quartet_divergence"] - 0.8) < 1e-9

    def test_second_binary_vs_polytomy(self):
        """((a,c),(b,(d,e))) vs (a,b,c,(d,e))."""
        data = run_tool("((a,c),(b,(d,e)));\n(a,b,c,(d,e));\n")
        p = get_pair(data, 0, 1)
        assert p["Q"] == 5
        assert p["s"] == 3
        assert p["d"] == 0
        assert p["r1"] == 2
        assert p["r2"] == 0
        assert p["u"] == 0


# ---------------------------------------------------------------------------
# 8-leaf trees -- exact golden values
# ---------------------------------------------------------------------------
class TestEightLeaf:

    def test_similar_binary_trees(self):
        """Trees differ only in one split: {a,b,c} vs {a,b,d}."""
        t0 = "((a,b),(c,(d,((e,f),(g,h)))));"
        t1 = "((a,b),(d,(c,((e,f),(g,h)))));"
        data = run_tool(f"{t0}\n{t1}\n")
        p = get_pair(data, 0, 1)
        assert p["Q"] == 70
        assert p["s"] == 62
        assert p["d"] == 8
        assert p["r1"] == 0
        assert p["r2"] == 0
        assert p["u"] == 0
        m = p["metrics"]
        assert abs(m["do_not_conflict"] - 62.0 / 70.0) < 1e-9
        assert abs(m["explicitly_agree"] - 62.0 / 70.0) < 1e-9
        assert abs(m["marczewski_steinhaus"] - 62.0 / 78.0) < 1e-9

    def test_binary_vs_polytomy(self):
        """Fully resolved vs heavily polytomous tree."""
        t0 = "((a,b),(c,(d,((e,f),(g,h)))));"
        t2 = "((a,b),((c,d),e,f,g,h));"
        data = run_tool(f"{t0}\n{t2}\n")
        p = get_pair(data, 0, 1)
        assert p["Q"] == 70
        assert p["s"] == 21
        assert p["d"] == 8
        assert p["r1"] == 41
        assert p["r2"] == 0
        assert p["u"] == 0
        m = p["metrics"]
        assert abs(m["do_not_conflict"] - 62.0 / 70.0) < 1e-9
        assert abs(m["explicitly_agree"] - 21.0 / 70.0) < 1e-9
        assert abs(m["strict_joint_assertions"] - 21.0 / 29.0) < 1e-9
        assert abs(m["steel_penny"] - 21.0 / 70.0) < 1e-9
        assert abs(m["quartet_divergence"] - 83.0 / 140.0) < 1e-9

    def test_self_comparison(self):
        t = "((a,b),(c,(d,((e,f),(g,h)))));"
        data = run_tool(f"{t}\n{t}\n")
        p = get_pair(data, 0, 1)
        assert p["Q"] == 70
        assert p["s"] == 70
        assert p["d"] == 0
        assert p["r1"] == 0
        assert p["r2"] == 0
        assert p["u"] == 0
        for k, v in p["metrics"].items():
            assert v == 1.0, f"Metric {k} should be 1.0 for identical trees"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases:

    def test_branch_lengths_ignored(self):
        data = run_tool(
            "((a:0.1,b:0.2):0.3,(c:0.1,d:0.2):0.3);\n((a,b),(c,d));\n"
        )
        p = get_pair(data, 0, 1)
        assert p["s"] == 1
        assert p["d"] == 0

    def test_different_leaf_order(self):
        data = run_tool("((b,a),(d,c));\n((a,b),(c,d));\n")
        p = get_pair(data, 0, 1)
        assert p["s"] == 1
        assert p["d"] == 0

    def test_internal_labels_ignored(self):
        data = run_tool("((a,b)X,(c,d)Y)Z;\n((a,b),(c,d));\n")
        p = get_pair(data, 0, 1)
        assert p["s"] == 1
        assert p["d"] == 0

    def test_trifurcation_at_root(self):
        """(a,b,(c,d)) is topologically identical to ((a,b),(c,d))."""
        data = run_tool("(a,b,(c,d));\n((a,b),(c,d));\n")
        p = get_pair(data, 0, 1)
        assert p["s"] == 1
        assert p["d"] == 0

    def test_pectinate_equivalent(self):
        """(a,(b,(c,d))) has same topology as ((a,b),(c,d)) for 4 leaves."""
        data = run_tool("(a,(b,(c,d)));\n((a,b),(c,d));\n")
        p = get_pair(data, 0, 1)
        assert p["s"] == 1
        assert p["d"] == 0


# ---------------------------------------------------------------------------
# Structural properties
# ---------------------------------------------------------------------------
class TestProperties:

    def test_sum_equals_Q(self):
        """s + d + r1 + r2 + u = Q for all pairs."""
        trees = "((a,b),(c,(d,e)));\n((a,c),(b,(d,e)));\n(a,b,c,(d,e));\n"
        data = run_tool(trees)
        for p in data["pairwise"]:
            total = p["s"] + p["d"] + p["r1"] + p["r2"] + p["u"]
            assert total == p["Q"], f"Sum {total} != Q {p['Q']}"

    def test_symmetry_r1_r2_swap(self):
        """Swapping tree order swaps r1 and r2, keeps s/d/u."""
        data_ab = run_tool("((a,b),(c,(d,e)));\n(a,b,c,(d,e));\n")
        data_ba = run_tool("(a,b,c,(d,e));\n((a,b),(c,(d,e)));\n")
        p_ab = get_pair(data_ab, 0, 1)
        p_ba = get_pair(data_ba, 0, 1)
        assert p_ab["s"] == p_ba["s"]
        assert p_ab["d"] == p_ba["d"]
        assert p_ab["r1"] == p_ba["r2"]
        assert p_ab["r2"] == p_ba["r1"]
        assert p_ab["u"] == p_ba["u"]

    def test_metric_bounds(self):
        """All non-null metrics in [0, 1]."""
        t0 = "((a,b),(c,(d,((e,f),(g,h)))));"
        t1 = "((a,b),(d,(c,((e,f),(g,h)))));"
        t2 = "((a,b),((c,d),e,f,g,h));"
        data = run_tool(f"{t0}\n{t1}\n{t2}\n")
        for p in data["pairwise"]:
            for k, v in p["metrics"].items():
                if v is not None:
                    assert 0.0 <= v <= 1.0, f"{k}={v} out of [0,1]"

    def test_multiple_pairs_count(self):
        trees = "((a,b),(c,d));\n((a,c),(b,d));\n((a,d),(b,c));\n(a,b,c,d);\n"
        data = run_tool(trees)
        assert data["num_trees"] == 4
        assert len(data["pairwise"]) == 6  # C(4,2)


# ---------------------------------------------------------------------------
# Large tree tests (performance and correctness)
# ---------------------------------------------------------------------------
class TestLargeTree:

    def test_80_leaf_self_comparison(self):
        """Self-comparison of an 80-leaf tree: all metrics = 1."""
        labels = [f"t{i}" for i in range(1, 81)]
        t = make_balanced(labels) + ";\n"
        data = run_tool(t + t, timeout=60)
        p = get_pair(data, 0, 1)
        Q = comb(80, 4)
        assert p["Q"] == Q
        assert p["s"] == Q
        assert p["d"] == 0
        assert p["r1"] == 0
        assert p["r2"] == 0
        assert p["u"] == 0
        for k, v in p["metrics"].items():
            assert v == 1.0, f"Metric {k} should be 1.0"

    def test_80_leaf_binary_pair(self):
        """Two different fully-binary 80-leaf trees: r1=r2=u=0, s+d=Q."""
        labels = [f"t{i}" for i in range(1, 81)]
        t1 = make_pectinate(labels) + ";\n"
        t2 = make_balanced(labels) + ";\n"
        data = run_tool(t1 + t2, timeout=60)
        p = get_pair(data, 0, 1)
        Q = comb(80, 4)
        assert p["Q"] == Q
        assert p["r1"] == 0
        assert p["r2"] == 0
        assert p["u"] == 0
        assert p["s"] + p["d"] == Q
        assert p["s"] > 0
        assert p["d"] > 0

    def test_80_leaf_three_trees(self):
        """Three 80-leaf trees must complete within timeout."""
        labels = [f"t{i}" for i in range(1, 81)]
        t1 = make_pectinate(labels) + ";\n"
        t2 = make_balanced(labels) + ";\n"
        t3 = make_pectinate(list(reversed(labels))) + ";\n"
        start = time.time()
        data = run_tool(t1 + t2 + t3, timeout=90)
        elapsed = time.time() - start
        assert elapsed < 90, f"Took {elapsed:.1f}s, over 90s limit"
        assert len(data["pairwise"]) == 3
        for p in data["pairwise"]:
            total = p["s"] + p["d"] + p["r1"] + p["r2"] + p["u"]
            assert total == p["Q"]

    def test_80_leaf_polytomy_pair(self):
        """80-leaf tree vs star-like polytomy: r2=0, u>0."""
        labels = [f"t{i}" for i in range(1, 81)]
        t_binary = make_balanced(labels) + ";\n"
        # Star tree: all leaves directly under root
        t_star = "(" + ",".join(labels) + ");\n"
        data = run_tool(t_binary + t_star, timeout=60)
        p = get_pair(data, 0, 1)
        Q = comb(80, 4)
        assert p["Q"] == Q
        assert p["s"] == 0
        assert p["d"] == 0
        assert p["r2"] == 0
        assert p["u"] == 0
        assert p["r1"] == Q
        total = p["s"] + p["d"] + p["r1"] + p["r2"] + p["u"]
        assert total == Q


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------
class TestOutputFormat:

    def test_required_fields(self):
        data = run_tool("((a,b),(c,d));\n((a,c),(b,d));\n")
        assert "num_trees" in data
        assert "leaf_labels" in data
        assert "pairwise" in data
        assert data["num_trees"] == 2
        assert data["leaf_labels"] == ["a", "b", "c", "d"]
        p = data["pairwise"][0]
        assert "i" in p and "j" in p
        assert "Q" in p and "s" in p and "d" in p
        assert "r1" in p and "r2" in p and "u" in p
        assert "metrics" in p
        expected_keys = {
            "do_not_conflict",
            "explicitly_agree",
            "strict_joint_assertions",
            "semi_strict_joint_assertions",
            "symmetric_difference",
            "marczewski_steinhaus",
            "steel_penny",
            "quartet_divergence",
        }
        assert set(p["metrics"].keys()) == expected_keys

    def test_leaf_labels_sorted(self):
        data = run_tool("((d,c),(b,a));\n((a,b),(c,d));\n")
        assert data["leaf_labels"] == ["a", "b", "c", "d"]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class TestErrors:

    def test_mismatched_leaves(self):
        rc = run_tool("((a,b),(c,d));\n((a,b),(c,e));\n", expect_fail=True)
        assert rc != 0

    def test_wrong_args(self):
        result = subprocess.run(
            ["python3", TOOL],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode != 0
