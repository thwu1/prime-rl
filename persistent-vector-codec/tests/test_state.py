import subprocess
import json
import os
import pytest


TOOL = "/app/pool_tool.py"
POOL1 = "/app/pools/pool1.json"
POOL2 = "/app/pools/pool2.json"
POOL3 = "/app/pools/pool3.json"
POOL4 = "/app/pools/pool4.json"


def run_tool(*args):
    """Run pool_tool.py with the given arguments and return stdout."""
    result = subprocess.run(
        ["python3", TOOL] + list(args),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"pool_tool.py failed with exit code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# reconstruct tests — pool1 (B=1, BL=1, M=2, L=2)
# ---------------------------------------------------------------------------

class TestReconstructPool1:
    """Verify reconstruction of all 5 vectors from pool1 (B=1, BL=1)."""

    def _get(self):
        return json.loads(run_tool("reconstruct", POOL1))

    def test_vector_count(self):
        output = self._get()
        assert len(output) == 5

    def test_v0(self):
        assert self._get()[0] == [10, 20, 30, 40]

    def test_v1(self):
        assert self._get()[1] == [10, 20, 30, 40, 50, 60]

    def test_v2_identical_to_v1(self):
        out = self._get()
        assert out[2] == out[1]
        assert out[2] == [10, 20, 30, 40, 50, 60]

    def test_v3(self):
        assert self._get()[3] == [99, 20, 30, 40, 50, 60]

    def test_v4_depth2(self):
        assert self._get()[4] == [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]


class TestReconstructPool2:
    """Verify reconstruction from pool2 (B=2, BL=2, branching factor 4)."""

    def _get(self):
        return json.loads(run_tool("reconstruct", POOL2))

    def test_v0(self):
        assert self._get()[0] == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_v1(self):
        assert self._get()[1] == list(range(1, 21))

    def test_v2_depth2(self):
        assert self._get()[2] == list(range(1, 25))

    def test_v3_null_root(self):
        assert self._get()[3] == [100, 200, 300]


class TestReconstructPool3:
    """Verify reconstruction from pool3 (B=1, BL=2, M=2, L=4) with depth-3 trees."""

    def _get(self):
        return json.loads(run_tool("reconstruct", POOL3))

    def test_vector_count(self):
        assert len(self._get()) == 4

    def test_v0_depth1(self):
        """8 elements, depth-1 tree, 1 body leaf."""
        assert self._get()[0] == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_v1_depth2(self):
        """20 elements, depth-2 tree, 4 body leaves."""
        assert self._get()[1] == list(range(1, 21))

    def test_v2_depth3(self):
        """36 elements, depth-3 tree, 8 body leaves."""
        assert self._get()[2] == list(range(1, 37))

    def test_v3_modified(self):
        """Like v1 but element 0 changed to 77."""
        expected = [77] + list(range(2, 21))
        assert self._get()[3] == expected


class TestReconstructPool4:
    """Verify reconstruction from pool4 (B=1, BL=2)."""

    def _get(self):
        return json.loads(run_tool("reconstruct", POOL4))

    def test_vector_count(self):
        assert len(self._get()) == 2

    def test_v0(self):
        assert self._get()[0] == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_v1_null_root(self):
        assert self._get()[1] == [41, 42, 43]


# ---------------------------------------------------------------------------
# sharing tests — pool1
# ---------------------------------------------------------------------------

class TestSharing:
    """Verify sharing analysis on pool1."""

    def _get(self):
        return json.loads(run_tool("sharing", POOL1))

    def test_leaf_100_shared_across_v0_v1_v2_v4(self):
        sharing = self._get()
        assert sorted(sharing["leaves"]["100"]) == [0, 1, 2, 4]

    def test_leaf_101_shared_by_all_vectors(self):
        sharing = self._get()
        assert sorted(sharing["leaves"]["101"]) == [0, 1, 2, 3, 4]

    def test_leaf_102_shared(self):
        sharing = self._get()
        assert sorted(sharing["leaves"]["102"]) == [1, 2, 3, 4]

    def test_leaf_103_unique_to_v3(self):
        sharing = self._get()
        assert sharing["leaves"]["103"] == [3]

    def test_leaf_104_unique_to_v4(self):
        sharing = self._get()
        assert sharing["leaves"]["104"] == [4]

    def test_leaf_105_unique_to_v4(self):
        sharing = self._get()
        assert sharing["leaves"]["105"] == [4]

    def test_inner_200_unique_to_v0(self):
        sharing = self._get()
        assert sharing["inners"]["200"] == [0]

    def test_inner_201_shared_v1_v2_v4(self):
        sharing = self._get()
        assert sorted(sharing["inners"]["201"]) == [1, 2, 4]

    def test_inner_202_unique_to_v3(self):
        sharing = self._get()
        assert sharing["inners"]["202"] == [3]

    def test_inner_207_unique_to_v4(self):
        sharing = self._get()
        assert sharing["inners"]["207"] == [4]

    def test_all_leaf_ids_present(self):
        sharing = self._get()
        assert sorted(sharing["leaves"].keys()) == sorted(
            ["100", "101", "102", "103", "104", "105"]
        )

    def test_all_inner_ids_present(self):
        sharing = self._get()
        assert sorted(sharing["inners"].keys()) == sorted(
            ["200", "201", "202", "206", "207"]
        )


# ---------------------------------------------------------------------------
# sharing tests — pool3
# ---------------------------------------------------------------------------

class TestSharingPool3:
    """Verify sharing analysis on pool3 (depth-3 trees with extensive sharing)."""

    def _get(self):
        return json.loads(run_tool("sharing", POOL3))

    def test_leaf_300_shared_v0_v1_v2(self):
        sharing = self._get()
        assert sorted(sharing["leaves"]["300"]) == [0, 1, 2]

    def test_leaf_301_shared_all(self):
        sharing = self._get()
        assert sorted(sharing["leaves"]["301"]) == [0, 1, 2, 3]

    def test_leaf_302_shared_v1_v2_v3(self):
        sharing = self._get()
        assert sorted(sharing["leaves"]["302"]) == [1, 2, 3]

    def test_leaf_304_shared_as_body_and_tail(self):
        """L304 is tail for v1 and v3, and body leaf (via I404) for v2."""
        sharing = self._get()
        assert sorted(sharing["leaves"]["304"]) == [1, 2, 3]

    def test_leaf_305_unique_to_v2(self):
        sharing = self._get()
        assert sharing["leaves"]["305"] == [2]

    def test_leaf_309_unique_to_v3(self):
        sharing = self._get()
        assert sharing["leaves"]["309"] == [3]

    def test_inner_401_shared_v1_v2(self):
        sharing = self._get()
        assert sorted(sharing["inners"]["401"]) == [1, 2]

    def test_inner_402_shared_v1_v2_v3(self):
        sharing = self._get()
        assert sorted(sharing["inners"]["402"]) == [1, 2, 3]

    def test_inner_403_shared_v1_v2(self):
        sharing = self._get()
        assert sorted(sharing["inners"]["403"]) == [1, 2]

    def test_inner_407_unique_to_v2(self):
        sharing = self._get()
        assert sharing["inners"]["407"] == [2]

    def test_inner_409_unique_to_v3(self):
        sharing = self._get()
        assert sharing["inners"]["409"] == [3]


# ---------------------------------------------------------------------------
# transform tests — pool1
# ---------------------------------------------------------------------------

class TestTransform:
    """Verify transform preserves topology and transforms values."""

    def _do_transform(self, expr="x * 3"):
        output_path = "/tmp/transformed_pool1.json"
        run_tool("transform", POOL1, expr, "-o", output_path)
        return output_path

    def test_topology_inners_unchanged(self):
        path = self._do_transform()
        with open(path) as f:
            transformed = json.load(f)
        with open(POOL1) as f:
            original = json.load(f)
        assert transformed["inners"] == original["inners"]

    def test_topology_vectors_unchanged(self):
        path = self._do_transform()
        with open(path) as f:
            transformed = json.load(f)
        with open(POOL1) as f:
            original = json.load(f)
        assert transformed["vectors"] == original["vectors"]

    def test_topology_branching_unchanged(self):
        path = self._do_transform()
        with open(path) as f:
            transformed = json.load(f)
        with open(POOL1) as f:
            original = json.load(f)
        assert transformed["B"] == original["B"]
        assert transformed["BL"] == original["BL"]

    def test_leaf_ids_preserved(self):
        path = self._do_transform()
        with open(path) as f:
            transformed = json.load(f)
        with open(POOL1) as f:
            original = json.load(f)
        orig_ids = sorted([e[0] for e in original["leaves"]])
        trans_ids = sorted([e[0] for e in transformed["leaves"]])
        assert trans_ids == orig_ids

    def test_reconstruct_v0_after_transform(self):
        path = self._do_transform("x * 3")
        output = json.loads(run_tool("reconstruct", path))
        assert output[0] == [30, 60, 90, 120]

    def test_reconstruct_v3_after_transform(self):
        path = self._do_transform("x * 3")
        output = json.loads(run_tool("reconstruct", path))
        assert output[3] == [297, 60, 90, 120, 150, 180]

    def test_reconstruct_v4_after_transform(self):
        path = self._do_transform("x * 3")
        output = json.loads(run_tool("reconstruct", path))
        assert output[4] == [30, 60, 90, 120, 150, 180, 210, 240, 270, 300]


# ---------------------------------------------------------------------------
# diff tests — pool1
# ---------------------------------------------------------------------------

class TestDiff:
    """Verify structural diff with tree-aware short-circuiting."""

    def test_diff_v1_v3_changes(self):
        output = json.loads(run_tool("diff", POOL1, "1", "3"))
        changes = output["changes"]
        assert len(changes) == 1
        assert changes[0]["index"] == 0
        assert changes[0]["old"] == 10
        assert changes[0]["new"] == 99

    def test_diff_v1_v3_stats_compared(self):
        output = json.loads(run_tool("diff", POOL1, "1", "3"))
        assert output["stats"]["elements_compared"] == 2

    def test_diff_v1_v3_stats_skipped(self):
        output = json.loads(run_tool("diff", POOL1, "1", "3"))
        assert output["stats"]["elements_skipped"] == 4

    def test_diff_v1_v3_stats_total(self):
        output = json.loads(run_tool("diff", POOL1, "1", "3"))
        assert output["stats"]["total_elements"] == 6

    def test_diff_identical_v1_v2(self):
        """v1 and v2 share all nodes: zero changes, all skipped."""
        output = json.loads(run_tool("diff", POOL1, "1", "2"))
        assert len(output["changes"]) == 0
        assert output["stats"]["elements_compared"] == 0
        assert output["stats"]["elements_skipped"] == 6

    def test_diff_symmetric(self):
        """diff(v3, v1) has reversed old/new values."""
        output = json.loads(run_tool("diff", POOL1, "3", "1"))
        changes = output["changes"]
        assert len(changes) == 1
        assert changes[0]["index"] == 0
        assert changes[0]["old"] == 99
        assert changes[0]["new"] == 10

    def test_diff_v0_v0_self(self):
        """Diffing a vector with itself: no changes."""
        output = json.loads(run_tool("diff", POOL1, "0", "0"))
        assert len(output["changes"]) == 0
        assert output["stats"]["elements_compared"] == 0
        assert output["stats"]["elements_skipped"] == 4


# ---------------------------------------------------------------------------
# diff tests — pool3
# ---------------------------------------------------------------------------

class TestDiffPool3:
    """Verify structural diff on pool3 with depth-2 trees and shared subtrees."""

    def test_diff_v1_v3_changes(self):
        """v1 and v3 differ only at element 0 (1 vs 77)."""
        output = json.loads(run_tool("diff", POOL3, "1", "3"))
        changes = output["changes"]
        assert len(changes) == 1
        assert changes[0]["index"] == 0
        assert changes[0]["old"] == 1
        assert changes[0]["new"] == 77

    def test_diff_v1_v3_stats(self):
        """4 elements compared (one leaf), 16 skipped (shared leaf + shared inner + shared tail)."""
        output = json.loads(run_tool("diff", POOL3, "1", "3"))
        stats = output["stats"]
        assert stats["elements_compared"] == 4
        assert stats["elements_skipped"] == 16
        assert stats["total_elements"] == 20

    def test_diff_v1_v1_self(self):
        """Self-diff: all 20 elements skipped."""
        output = json.loads(run_tool("diff", POOL3, "1", "1"))
        assert len(output["changes"]) == 0
        assert output["stats"]["elements_compared"] == 0
        assert output["stats"]["elements_skipped"] == 20


# ---------------------------------------------------------------------------
# merge tests — pool3 + pool4
# ---------------------------------------------------------------------------

class TestMerge:
    """Verify merging pool3 and pool4 with structural deduplication."""

    MERGED_PATH = "/tmp/merged_pool.json"

    @classmethod
    def _do_merge(cls):
        run_tool("merge", POOL3, POOL4, "-o", cls.MERGED_PATH)
        with open(cls.MERGED_PATH) as f:
            return json.load(f)

    def test_merge_vector_count(self):
        merged = self._do_merge()
        assert len(merged["vectors"]) == 6

    def test_merge_encoding_params(self):
        merged = self._do_merge()
        assert merged["B"] == 1
        assert merged["BL"] == 2

    def test_merge_leaf_deduplication(self):
        """pool3 has 10 leaves, pool4 has 3. Two overlap -> 11 unique."""
        merged = self._do_merge()
        assert len(merged["leaves"]) == 11

    def test_merge_inner_deduplication(self):
        """pool3 has 10 inners, pool4 has 1. One overlaps -> 10 unique."""
        merged = self._do_merge()
        assert len(merged["inners"]) == 10

    def test_merge_leaf_ids_contiguous(self):
        merged = self._do_merge()
        ids = sorted([e[0] for e in merged["leaves"]])
        assert ids == list(range(len(ids)))

    def test_merge_inner_ids_contiguous(self):
        merged = self._do_merge()
        ids = sorted([e[0] for e in merged["inners"]])
        assert ids == list(range(len(ids)))

    def test_merge_reconstruct_v0(self):
        """First pool3 vector: [1..8]."""
        self._do_merge()
        output = json.loads(run_tool("reconstruct", self.MERGED_PATH))
        assert output[0] == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_merge_reconstruct_v1(self):
        """Second pool3 vector: [1..20]."""
        self._do_merge()
        output = json.loads(run_tool("reconstruct", self.MERGED_PATH))
        assert output[1] == list(range(1, 21))

    def test_merge_reconstruct_v2(self):
        """Third pool3 vector: [1..36]."""
        self._do_merge()
        output = json.loads(run_tool("reconstruct", self.MERGED_PATH))
        assert output[2] == list(range(1, 37))

    def test_merge_reconstruct_v3(self):
        """Fourth pool3 vector: [77, 2..20]."""
        self._do_merge()
        output = json.loads(run_tool("reconstruct", self.MERGED_PATH))
        assert output[3] == [77] + list(range(2, 21))

    def test_merge_reconstruct_v4(self):
        """First pool4 vector: [1..8] (same content as v0)."""
        self._do_merge()
        output = json.loads(run_tool("reconstruct", self.MERGED_PATH))
        assert output[4] == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_merge_reconstruct_v5(self):
        """Second pool4 vector: [41, 42, 43]."""
        self._do_merge()
        output = json.loads(run_tool("reconstruct", self.MERGED_PATH))
        assert output[5] == [41, 42, 43]

    def test_merge_v0_v4_share_structure(self):
        """v0 (pool3) and v4 (pool4) have identical content -> same root and tail."""
        merged = self._do_merge()
        v0, v4 = merged["vectors"][0], merged["vectors"][4]
        assert v0["root"] == v4["root"]
        assert v0["tail"] == v4["tail"]
