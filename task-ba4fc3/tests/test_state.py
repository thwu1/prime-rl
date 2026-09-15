
import subprocess
import json
import os
import tempfile
import sqlite3
import pytest

TOOL = "/app/rbt_pool.py"


def run_tool(*args):
    cmd = ["python3", TOOL] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def write_temp_json(data):
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    return path


def build_pool(ops):
    ops_file = write_temp_json(ops)
    fd, out_file = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    r = run_tool("build", ops_file, "-o", out_file)
    os.unlink(ops_file)
    assert r.returncode == 0, f"build failed: {r.stderr}"
    with open(out_file) as f:
        pool = json.load(f)
    os.unlink(out_file)
    return pool


def reconstruct(pool):
    pool_file = write_temp_json(pool)
    r = run_tool("reconstruct", pool_file)
    os.unlink(pool_file)
    assert r.returncode == 0, f"reconstruct failed: {r.stderr}"
    return json.loads(r.stdout)


def analyze(pool):
    pool_file = write_temp_json(pool)
    r = run_tool("analyze", pool_file)
    os.unlink(pool_file)
    assert r.returncode == 0, f"analyze failed: {r.stderr}"
    return json.loads(r.stdout)


def validate(pool):
    pool_file = write_temp_json(pool)
    r = run_tool("validate", pool_file)
    os.unlink(pool_file)
    return r.returncode == 0, r.stdout.strip()


def transform(pool, spec):
    pool_file = write_temp_json(pool)
    spec_file = write_temp_json(spec)
    fd, out_file = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    r = run_tool("transform", pool_file, spec_file, "-o", out_file)
    os.unlink(pool_file)
    os.unlink(spec_file)
    assert r.returncode == 0, f"transform failed: {r.stderr}"
    with open(out_file) as f:
        result = json.load(f)
    os.unlink(out_file)
    return result


def visualize(pool, svg_path):
    pool_file = write_temp_json(pool)
    r = run_tool("visualize", pool_file, "-o", svg_path)
    os.unlink(pool_file)
    return r


def store_pool(pool, db_path):
    pool_file = write_temp_json(pool)
    r = run_tool("store", pool_file, "-o", db_path)
    os.unlink(pool_file)
    return r


def load_pool(db_path):
    r = run_tool("load", db_path)
    return r


# ---------------------------------------------------------------------------
# Round-trip tests: build -> reconstruct -> verify element contents
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_basic_create_b1_bl1(self):
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1", "elements": [10, 20, 30, 40]}
            ],
        }
        pool = build_pool(ops)
        result = reconstruct(pool)
        assert result["v1"] == [10, 20, 30, 40]

    def test_push_back_b1_bl1(self):
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]},
                {"op": "push_back", "name": "v2", "source": "v1", "value": 5},
                {"op": "push_back", "name": "v3", "source": "v2", "value": 6},
            ],
        }
        pool = build_pool(ops)
        result = reconstruct(pool)
        assert result["v1"] == [1, 2, 3, 4]
        assert result["v2"] == [1, 2, 3, 4, 5]
        assert result["v3"] == [1, 2, 3, 4, 5, 6]

    def test_set_tree_element(self):
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]},
                {"op": "set", "name": "v2", "source": "v1", "index": 0, "value": 99},
            ],
        }
        pool = build_pool(ops)
        result = reconstruct(pool)
        assert result["v1"] == [1, 2, 3, 4]
        assert result["v2"] == [99, 2, 3, 4]

    def test_set_tail_element(self):
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]},
                {"op": "set", "name": "v2", "source": "v1", "index": 3, "value": 99},
            ],
        }
        pool = build_pool(ops)
        result = reconstruct(pool)
        assert result["v1"] == [1, 2, 3, 4]
        assert result["v2"] == [1, 2, 3, 99]

    def test_deep_tree_b1_bl1(self):
        """18 elements with B=1 BL=1 requires depth-3 tree."""
        elements = list(range(1, 19))
        ops = {"B": 1, "BL": 1, "operations": [
            {"op": "create", "name": "v1", "elements": elements}
        ]}
        pool = build_pool(ops)
        result = reconstruct(pool)
        assert result["v1"] == elements

    def test_b2_bl2(self):
        elements = list(range(1, 25))
        ops = {"B": 2, "BL": 2, "operations": [
            {"op": "create", "name": "v1", "elements": elements}
        ]}
        pool = build_pool(ops)
        result = reconstruct(pool)
        assert result["v1"] == elements

    def test_b2_bl3(self):
        elements = list(range(1, 101))
        ops = {"B": 2, "BL": 3, "operations": [
            {"op": "create", "name": "v1", "elements": elements}
        ]}
        pool = build_pool(ops)
        result = reconstruct(pool)
        assert result["v1"] == elements

    def test_copy_operation(self):
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]},
                {"op": "copy", "name": "v2", "source": "v1"},
            ],
        }
        pool = build_pool(ops)
        result = reconstruct(pool)
        assert result["v1"] == [1, 2, 3, 4]
        assert result["v2"] == [1, 2, 3, 4]
        assert pool["named_vectors"]["v1"] == pool["named_vectors"]["v2"]

    def test_small_vector_no_tree(self):
        """Vector with <= ML elements has null root."""
        ops = {"B": 1, "BL": 1, "operations": [
            {"op": "create", "name": "v1", "elements": [42, 99]}
        ]}
        pool = build_pool(ops)
        result = reconstruct(pool)
        assert result["v1"] == [42, 99]
        vec_idx = pool["named_vectors"]["v1"]
        assert pool["pool"]["vectors"][vec_idx]["root"] is None

    def test_single_element(self):
        ops = {"B": 2, "BL": 2, "operations": [
            {"op": "create", "name": "v1", "elements": [7]}
        ]}
        pool = build_pool(ops)
        result = reconstruct(pool)
        assert result["v1"] == [7]

    def test_string_elements(self):
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1",
                 "elements": ["hello", "world", "foo", "bar"]}
            ],
        }
        pool = build_pool(ops)
        result = reconstruct(pool)
        assert result["v1"] == ["hello", "world", "foo", "bar"]


# ---------------------------------------------------------------------------
# Structural sharing tests
# ---------------------------------------------------------------------------

class TestStructuralSharing:
    def test_push_back_shares_nodes(self):
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]},
                {"op": "push_back", "name": "v2", "source": "v1", "value": 5},
                {"op": "push_back", "name": "v3", "source": "v2", "value": 6},
            ],
        }
        pool = build_pool(ops)
        stats = analyze(pool)
        assert stats["shared_nodes"] > 0
        assert stats["sharing_ratio"] > 0

    def test_set_shares_unchanged_subtree(self):
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]},
                {"op": "set", "name": "v2", "source": "v1",
                 "index": 3, "value": 99},
            ],
        }
        pool = build_pool(ops)
        stats = analyze(pool)
        # v1 and v2 share the root inner and tree leaf [1,2]
        assert stats["shared_nodes"] > 0

    def test_divergent_branches_share(self):
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]},
                {"op": "push_back", "name": "v2a", "source": "v1", "value": 5},
                {"op": "push_back", "name": "v2b", "source": "v2a", "value": 6},
                {"op": "push_back", "name": "v3a", "source": "v1", "value": 7},
                {"op": "push_back", "name": "v3b", "source": "v3a", "value": 8},
            ],
        }
        pool = build_pool(ops)
        stats = analyze(pool)
        assert stats["shared_nodes"] >= 2

    def test_pool_deduplicates_shared_leaves(self):
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1",
                 "elements": [1, 2, 3, 4, 5, 6]},
                {"op": "push_back", "name": "v2", "source": "v1", "value": 7},
                {"op": "push_back", "name": "v3", "source": "v2", "value": 8},
            ],
        }
        pool = build_pool(ops)
        total_stored = sum(len(leaf[1]) for leaf in pool["pool"]["leaves"])
        naive_total = 6 + 7 + 8
        assert total_stored < naive_total


# ---------------------------------------------------------------------------
# Transform tests
# ---------------------------------------------------------------------------

class TestTransform:
    def test_multiply(self):
        ops = {"B": 1, "BL": 1, "operations": [
            {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]}
        ]}
        pool = build_pool(ops)
        xformed = transform(pool, {"type": "multiply", "factor": 10})
        result = reconstruct(xformed)
        assert result["v1"] == [10, 20, 30, 40]

    def test_add(self):
        ops = {"B": 1, "BL": 1, "operations": [
            {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]}
        ]}
        pool = build_pool(ops)
        xformed = transform(pool, {"type": "add", "value": 100})
        result = reconstruct(xformed)
        assert result["v1"] == [101, 102, 103, 104]

    def test_uppercase(self):
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1",
                 "elements": ["hello", "world", "foo", "bar"]}
            ],
        }
        pool = build_pool(ops)
        xformed = transform(pool, {"type": "uppercase"})
        result = reconstruct(xformed)
        assert result["v1"] == ["HELLO", "WORLD", "FOO", "BAR"]

    def test_negate(self):
        ops = {"B": 2, "BL": 2, "operations": [
            {"op": "create", "name": "v1", "elements": [1, -2, 3, -4, 5]}
        ]}
        pool = build_pool(ops)
        xformed = transform(pool, {"type": "negate"})
        result = reconstruct(xformed)
        assert result["v1"] == [-1, 2, -3, 4, -5]

    def test_transform_preserves_inner_structure(self):
        ops = {"B": 1, "BL": 1, "operations": [
            {"op": "create", "name": "v1", "elements": [1, 2, 3, 4, 5, 6]}
        ]}
        pool = build_pool(ops)
        xformed = transform(pool, {"type": "multiply", "factor": 2})
        assert pool["pool"]["inners"] == xformed["pool"]["inners"]
        assert pool["pool"]["vectors"] == xformed["pool"]["vectors"]
        assert pool["pool"]["leaves"] != xformed["pool"]["leaves"]

    def test_transform_preserves_sharing_stats(self):
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]},
                {"op": "push_back", "name": "v2", "source": "v1", "value": 5},
                {"op": "push_back", "name": "v3", "source": "v2", "value": 6},
            ],
        }
        pool = build_pool(ops)
        stats_before = analyze(pool)
        xformed = transform(pool, {"type": "multiply", "factor": 3})
        stats_after = analyze(xformed)
        assert stats_before["shared_nodes"] == stats_after["shared_nodes"]
        assert stats_before["sharing_ratio"] == stats_after["sharing_ratio"]


# ---------------------------------------------------------------------------
# Validate tests
# ---------------------------------------------------------------------------

class TestValidate:
    def test_valid_pool(self):
        ops = {"B": 1, "BL": 1, "operations": [
            {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]}
        ]}
        pool = build_pool(ops)
        ok, _ = validate(pool)
        assert ok

    def test_dangling_reference(self):
        pool = {
            "named_vectors": {"v1": 0},
            "pool": {
                "B": 1, "BL": 1,
                "leaves": [[1, [1, 2]]],
                "inners": [[0, {"children": [1, 999], "relaxed": False}]],
                "vectors": [{"root": 0, "tail": 1}],
            },
        }
        ok, _ = validate(pool)
        assert not ok

    def test_overlapping_leaf_inner_ids(self):
        pool = {
            "named_vectors": {"v1": 0},
            "pool": {
                "B": 1, "BL": 1,
                "leaves": [[0, [1, 2]], [1, [3, 4]]],
                "inners": [[0, {"children": [1], "relaxed": False}]],
                "vectors": [{"root": 0, "tail": 1}],
            },
        }
        ok, _ = validate(pool)
        assert not ok

    def test_leaf_exceeds_ml(self):
        pool = {
            "named_vectors": {"v1": 0},
            "pool": {
                "B": 1, "BL": 1,
                "leaves": [[0, [1, 2, 3, 4, 5]]],
                "inners": [],
                "vectors": [{"root": None, "tail": 0}],
            },
        }
        ok, _ = validate(pool)
        assert not ok

    def test_inner_exceeds_m(self):
        pool = {
            "named_vectors": {"v1": 0},
            "pool": {
                "B": 1, "BL": 1,
                "leaves": [
                    [1, [1, 2]], [2, [3, 4]], [3, [5, 6]], [4, [7, 8]],
                ],
                "inners": [
                    [0, {"children": [1, 2, 3], "relaxed": False}],
                ],
                "vectors": [{"root": 0, "tail": 4}],
            },
        }
        ok, _ = validate(pool)
        assert not ok

    def test_duplicate_leaf_id(self):
        pool = {
            "named_vectors": {"v1": 0},
            "pool": {
                "B": 1, "BL": 1,
                "leaves": [[1, [1, 2]], [1, [3, 4]]],
                "inners": [[0, {"children": [1], "relaxed": False}]],
                "vectors": [{"root": 0, "tail": 1}],
            },
        }
        ok, _ = validate(pool)
        assert not ok

    def test_root_references_leaf(self):
        """root must be an inner node, not a leaf."""
        pool = {
            "named_vectors": {"v1": 0},
            "pool": {
                "B": 1, "BL": 1,
                "leaves": [[1, [1, 2]], [2, [3, 4]]],
                "inners": [],
                "vectors": [{"root": 1, "tail": 2}],
            },
        }
        ok, _ = validate(pool)
        assert not ok


# ---------------------------------------------------------------------------
# Analyze tests
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_no_sharing_single_vector(self):
        ops = {"B": 1, "BL": 1, "operations": [
            {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]}
        ]}
        pool = build_pool(ops)
        stats = analyze(pool)
        assert stats["shared_nodes"] == 0
        assert stats["sharing_ratio"] == 0.0

    def test_sharing_with_push_back(self):
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]},
                {"op": "push_back", "name": "v2", "source": "v1", "value": 5},
                {"op": "push_back", "name": "v3", "source": "v2", "value": 6},
            ],
        }
        pool = build_pool(ops)
        stats = analyze(pool)
        assert stats["shared_nodes"] > 0
        assert stats["sharing_ratio"] > 0
        assert stats["naive_total_elements"] > stats["actual_stored_elements"]

    def test_sharing_divergent_branches(self):
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]},
                {"op": "push_back", "name": "v2a", "source": "v1", "value": 5},
                {"op": "push_back", "name": "v2b", "source": "v2a", "value": 6},
                {"op": "push_back", "name": "v3a", "source": "v1", "value": 7},
                {"op": "push_back", "name": "v3b", "source": "v3a", "value": 8},
            ],
        }
        pool = build_pool(ops)
        stats = analyze(pool)
        assert stats["shared_nodes"] >= 2


# ---------------------------------------------------------------------------
# Reconstruct from hand-crafted pool JSON
# ---------------------------------------------------------------------------

class TestReconstructFromPool:
    def test_example_pool_from_spec(self):
        """Reconstruct the example pool matching the CppCon slides."""
        example = {
            "named_vectors": {"v1": 0, "v2": 1, "v3": 1},
            "pool": {
                "B": 1, "BL": 1,
                "leaves": [
                    [1, ["c", "d"]], [2, ["a", "b"]], [4, ["e", "f"]],
                ],
                "inners": [
                    [0, {"children": [2], "relaxed": False}],
                    [3, {"children": [2, 1], "relaxed": False}],
                ],
                "vectors": [
                    {"root": 0, "tail": 1},
                    {"root": 3, "tail": 4},
                ],
            },
        }
        result = reconstruct(example)
        assert result["v1"] == ["a", "b", "c", "d"]
        assert result["v2"] == ["a", "b", "c", "d", "e", "f"]
        assert result["v3"] == ["a", "b", "c", "d", "e", "f"]

    def test_null_root_pool(self):
        pool = {
            "named_vectors": {"v1": 0},
            "pool": {
                "B": 1, "BL": 1,
                "leaves": [[0, [42, 99]]],
                "inners": [],
                "vectors": [{"root": None, "tail": 0}],
            },
        }
        result = reconstruct(pool)
        assert result["v1"] == [42, 99]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_many_sequential_push_backs(self):
        ops_list = [{"op": "create", "name": "v0", "elements": [0]}]
        for i in range(1, 20):
            ops_list.append({
                "op": "push_back", "name": f"v{i}",
                "source": f"v{i - 1}", "value": i,
            })
        ops = {"B": 2, "BL": 2, "operations": ops_list}
        pool = build_pool(ops)
        result = reconstruct(pool)
        for i in range(20):
            assert result[f"v{i}"] == list(range(i + 1)), f"v{i} mismatch"

    def test_set_chain(self):
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1",
                 "elements": [1, 2, 3, 4, 5, 6]},
                {"op": "set", "name": "v2", "source": "v1",
                 "index": 0, "value": 10},
                {"op": "set", "name": "v3", "source": "v2",
                 "index": 5, "value": 60},
                {"op": "set", "name": "v4", "source": "v3",
                 "index": 2, "value": 30},
            ],
        }
        pool = build_pool(ops)
        result = reconstruct(pool)
        assert result["v1"] == [1, 2, 3, 4, 5, 6]
        assert result["v2"] == [10, 2, 3, 4, 5, 6]
        assert result["v3"] == [10, 2, 3, 4, 5, 60]
        assert result["v4"] == [10, 2, 30, 4, 5, 60]

    def test_large_vector_b3_bl3(self):
        elements = list(range(500))
        ops = {"B": 3, "BL": 3, "operations": [
            {"op": "create", "name": "v1", "elements": elements}
        ]}
        pool = build_pool(ops)
        result = reconstruct(pool)
        assert result["v1"] == elements

    def test_b1_bl2_mixed(self):
        """Asymmetric B != BL."""
        elements = list(range(1, 33))
        ops = {"B": 1, "BL": 2, "operations": [
            {"op": "create", "name": "v1", "elements": elements}
        ]}
        pool = build_pool(ops)
        result = reconstruct(pool)
        assert result["v1"] == elements

    def test_set_in_deep_tree(self):
        """Set an element deep in a multi-level tree."""
        elements = list(range(1, 19))
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1", "elements": elements},
                {"op": "set", "name": "v2", "source": "v1",
                 "index": 0, "value": 999},
                {"op": "set", "name": "v3", "source": "v1",
                 "index": 15, "value": 888},
            ],
        }
        pool = build_pool(ops)
        result = reconstruct(pool)
        expected1 = list(range(1, 19))
        expected2 = list(range(1, 19))
        expected2[0] = 999
        expected3 = list(range(1, 19))
        expected3[15] = 888
        assert result["v1"] == expected1
        assert result["v2"] == expected2
        assert result["v3"] == expected3


# ---------------------------------------------------------------------------
# Visualize tests (GraphViz DOT -> SVG)
# ---------------------------------------------------------------------------

class TestVisualize:
    def test_produces_valid_svg(self):
        """visualize must produce a well-formed SVG file."""
        ops = {"B": 1, "BL": 1, "operations": [
            {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]}
        ]}
        pool = build_pool(ops)
        fd, svg_path = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        try:
            r = visualize(pool, svg_path)
            assert r.returncode == 0, f"visualize failed: {r.stderr}"
            with open(svg_path) as f:
                svg = f.read()
            assert "<svg" in svg, "Output is not SVG"
            assert "</svg>" in svg, "SVG is not closed"
            assert len(svg) > 100, "SVG suspiciously short"
        finally:
            if os.path.exists(svg_path):
                os.unlink(svg_path)

    def test_shared_nodes_highlighted(self):
        """Shared nodes must use fill color #ffd700."""
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]},
                {"op": "push_back", "name": "v2", "source": "v1", "value": 5},
            ],
        }
        pool = build_pool(ops)
        # Confirm there are shared nodes
        stats = analyze(pool)
        assert stats["shared_nodes"] > 0
        fd, svg_path = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        try:
            r = visualize(pool, svg_path)
            assert r.returncode == 0, f"visualize failed: {r.stderr}"
            with open(svg_path) as f:
                svg = f.read().lower()
            assert "#ffd700" in svg, "Shared nodes not highlighted with #ffd700"
        finally:
            if os.path.exists(svg_path):
                os.unlink(svg_path)

    def test_no_sharing_no_gold(self):
        """Pool with single vector should not have shared-node color."""
        ops = {"B": 1, "BL": 1, "operations": [
            {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]}
        ]}
        pool = build_pool(ops)
        fd, svg_path = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        try:
            r = visualize(pool, svg_path)
            assert r.returncode == 0, f"visualize failed: {r.stderr}"
            with open(svg_path) as f:
                svg = f.read().lower()
            assert "#ffd700" not in svg, "Single-vector pool should not have shared color"
        finally:
            if os.path.exists(svg_path):
                os.unlink(svg_path)

    def test_unique_leaf_color(self):
        """Unique leaf nodes must use fill color #90ee90."""
        ops = {"B": 1, "BL": 1, "operations": [
            {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]}
        ]}
        pool = build_pool(ops)
        fd, svg_path = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        try:
            r = visualize(pool, svg_path)
            assert r.returncode == 0, f"visualize failed: {r.stderr}"
            with open(svg_path) as f:
                svg = f.read().lower()
            assert "#90ee90" in svg, "Unique leaf color #90ee90 not found"
        finally:
            if os.path.exists(svg_path):
                os.unlink(svg_path)

    def test_vector_descriptors_present(self):
        """Vector descriptor nodes (ellipses) must appear in the SVG."""
        ops = {"B": 1, "BL": 1, "operations": [
            {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]},
            {"op": "push_back", "name": "v2", "source": "v1", "value": 5},
        ]}
        pool = build_pool(ops)
        fd, svg_path = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        try:
            r = visualize(pool, svg_path)
            assert r.returncode == 0, f"visualize failed: {r.stderr}"
            with open(svg_path) as f:
                svg = f.read().lower()
            # Vector descriptor fill color
            assert "#ffc0cb" in svg, "Vector descriptor color #ffc0cb not found"
        finally:
            if os.path.exists(svg_path):
                os.unlink(svg_path)


# ---------------------------------------------------------------------------
# Store / Load tests (SQLite round-trip)
# ---------------------------------------------------------------------------

class TestStoreLoad:
    def test_round_trip_simple(self):
        """store -> load -> reconstruct must yield original elements."""
        ops = {"B": 1, "BL": 1, "operations": [
            {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]}
        ]}
        pool = build_pool(ops)
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            r = store_pool(pool, db_path)
            assert r.returncode == 0, f"store failed: {r.stderr}"
            r = load_pool(db_path)
            assert r.returncode == 0, f"load failed: {r.stderr}"
            loaded = json.loads(r.stdout)
            result = reconstruct(loaded)
            assert result["v1"] == [1, 2, 3, 4]
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_round_trip_with_sharing(self):
        """Shared pools must survive the SQLite round-trip."""
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]},
                {"op": "push_back", "name": "v2", "source": "v1", "value": 5},
                {"op": "push_back", "name": "v3", "source": "v2", "value": 6},
            ],
        }
        pool = build_pool(ops)
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            r = store_pool(pool, db_path)
            assert r.returncode == 0, f"store failed: {r.stderr}"
            r = load_pool(db_path)
            assert r.returncode == 0, f"load failed: {r.stderr}"
            loaded = json.loads(r.stdout)
            result = reconstruct(loaded)
            assert result["v1"] == [1, 2, 3, 4]
            assert result["v2"] == [1, 2, 3, 4, 5]
            assert result["v3"] == [1, 2, 3, 4, 5, 6]
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_database_has_required_tables(self):
        """SQLite database must have the six normalized tables."""
        ops = {"B": 1, "BL": 1, "operations": [
            {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]}
        ]}
        pool = build_pool(ops)
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            r = store_pool(pool, db_path)
            assert r.returncode == 0, f"store failed: {r.stderr}"
            conn = sqlite3.connect(db_path)
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            conn.close()
            required = {"metadata", "leaf_nodes", "inner_nodes",
                        "inner_children", "vectors", "named_vectors"}
            missing = required - tables
            assert not missing, f"Missing tables: {missing}"
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_foreign_keys_defined(self):
        """inner_children must have a foreign key on inner_id."""
        ops = {"B": 1, "BL": 1, "operations": [
            {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]}
        ]}
        pool = build_pool(ops)
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            r = store_pool(pool, db_path)
            assert r.returncode == 0, f"store failed: {r.stderr}"
            conn = sqlite3.connect(db_path)
            fkeys = conn.execute(
                "PRAGMA foreign_key_list(inner_children)"
            ).fetchall()
            conn.close()
            assert len(fkeys) > 0, "inner_children has no foreign keys"
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_named_vectors_fk(self):
        """named_vectors must reference vectors via foreign key."""
        ops = {"B": 1, "BL": 1, "operations": [
            {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]}
        ]}
        pool = build_pool(ops)
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            r = store_pool(pool, db_path)
            assert r.returncode == 0, f"store failed: {r.stderr}"
            conn = sqlite3.connect(db_path)
            fkeys = conn.execute(
                "PRAGMA foreign_key_list(named_vectors)"
            ).fetchall()
            conn.close()
            assert len(fkeys) > 0, "named_vectors has no foreign keys"
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_metadata_stored(self):
        """B and BL must be stored in the metadata table."""
        ops = {"B": 2, "BL": 3, "operations": [
            {"op": "create", "name": "v1", "elements": list(range(20))}
        ]}
        pool = build_pool(ops)
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            r = store_pool(pool, db_path)
            assert r.returncode == 0, f"store failed: {r.stderr}"
            conn = sqlite3.connect(db_path)
            meta = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
            conn.close()
            assert meta["B"] == "2", f"B should be '2', got {meta.get('B')}"
            assert meta["BL"] == "3", f"BL should be '3', got {meta.get('BL')}"
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_store_load_preserves_analysis(self):
        """Sharing stats must be identical after store/load cycle."""
        ops = {
            "B": 1, "BL": 1,
            "operations": [
                {"op": "create", "name": "v1", "elements": [1, 2, 3, 4]},
                {"op": "push_back", "name": "v2", "source": "v1", "value": 5},
                {"op": "push_back", "name": "v3", "source": "v2", "value": 6},
            ],
        }
        pool = build_pool(ops)
        stats_before = analyze(pool)
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            r = store_pool(pool, db_path)
            assert r.returncode == 0, f"store failed: {r.stderr}"
            r = load_pool(db_path)
            assert r.returncode == 0, f"load failed: {r.stderr}"
            loaded = json.loads(r.stdout)
            stats_after = analyze(loaded)
            assert stats_before["shared_nodes"] == stats_after["shared_nodes"]
            assert stats_before["sharing_ratio"] == stats_after["sharing_ratio"]
            assert stats_before["total_nodes"] == stats_after["total_nodes"]
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_round_trip_string_elements(self):
        """String element types must survive SQLite round-trip."""
        ops = {"B": 1, "BL": 1, "operations": [
            {"op": "create", "name": "v1",
             "elements": ["alpha", "beta", "gamma", "delta"]}
        ]}
        pool = build_pool(ops)
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            r = store_pool(pool, db_path)
            assert r.returncode == 0, f"store failed: {r.stderr}"
            r = load_pool(db_path)
            assert r.returncode == 0, f"load failed: {r.stderr}"
            loaded = json.loads(r.stdout)
            result = reconstruct(loaded)
            assert result["v1"] == ["alpha", "beta", "gamma", "delta"]
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)
