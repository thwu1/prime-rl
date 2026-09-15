"""
Tests for Jepsen EDN history consistency checker.
Verifies /app/results.json classifications, graph metrics, cycle analysis,
SCC decomposition, and /app/graphs/ SVG output against hand-verified values.
"""

import json
import os
import pytest


EXPECTED = {
    "h1": {
        "committed_count": 7,
        "consistency_level": "strict-serializable",
        "g0": False,
        "g1c": False,
        "g2": False,
        "strict_serializable": True,
        "edge_counts": {"ww": 4, "wr": 10, "rw": 2},
        "shortest_cycle": None,
        "scc_count": 0,
        "scc_max_size": 0,
        "min_removal_count": 0,
        "min_removal_set": [],
    },
    "h2": {
        "committed_count": 4,
        "consistency_level": "anomalous",
        "g0": True,
        "g1c": True,
        "g2": True,
        "strict_serializable": False,
        "edge_counts": {"ww": 2, "wr": 4, "rw": 0},
        "shortest_cycle": [0, 1, 0],
        "scc_count": 1,
        "scc_max_size": 2,
        "min_removal_count": 1,
        "min_removal_set": [0],
    },
    "h3": {
        "committed_count": 5,
        "consistency_level": "read-uncommitted",
        "g0": False,
        "g1c": True,
        "g2": True,
        "strict_serializable": False,
        "edge_counts": {"ww": 2, "wr": 7, "rw": 3},
        "shortest_cycle": [0, 1, 0],
        "scc_count": 1,
        "scc_max_size": 2,
        "min_removal_count": 1,
        "min_removal_set": [0],
    },
    "h4": {
        "committed_count": 5,
        "consistency_level": "read-committed",
        "g0": False,
        "g1c": False,
        "g2": True,
        "strict_serializable": False,
        "edge_counts": {"ww": 2, "wr": 6, "rw": 4},
        "shortest_cycle": [0, 3, 0],
        "scc_count": 1,
        "scc_max_size": 4,
        "min_removal_count": 2,
        "min_removal_set": [0, 2],
    },
    "h5": {
        "committed_count": 5,
        "consistency_level": "serializable",
        "g0": False,
        "g1c": False,
        "g2": False,
        "strict_serializable": False,
        "edge_counts": {"ww": 1, "wr": 5, "rw": 2},
        "shortest_cycle": None,
        "scc_count": 0,
        "scc_max_size": 0,
        "min_removal_count": 0,
        "min_removal_set": [],
    },
    "h6": {
        "committed_count": 19,
        "consistency_level": "read-committed",
        "g0": False,
        "g1c": False,
        "g2": True,
        "strict_serializable": False,
        "edge_counts": {"ww": 11, "wr": 52, "rw": 10},
        "shortest_cycle": [12, 13, 12],
        "scc_count": 1,
        "scc_max_size": 2,
        "min_removal_count": 1,
        "min_removal_set": [12],
    },
}

ANOMALOUS_HISTORIES = ["h2", "h3", "h4", "h6"]


@pytest.fixture(scope="session")
def results():
    results_path = "/app/results.json"
    assert os.path.exists(results_path), (
        f"Results file not found at {results_path}. "
        "The checker must write analysis output to /app/results.json."
    )
    with open(results_path) as f:
        data = json.load(f)
    assert isinstance(data, dict), "results.json must contain a JSON object"
    return data


class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_all_histories_present(self, results):
        for name in EXPECTED:
            assert name in results, (
                f"Missing analysis for history '{name}' in results.json. "
                f"Found keys: {sorted(results.keys())}"
            )

    @pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
    def test_required_fields(self, results, history_name):
        entry = results.get(history_name, {})
        required = [
            "committed_count", "consistency_level", "g0", "g1c", "g2",
            "strict_serializable", "edge_counts", "shortest_cycle",
            "scc_count", "scc_max_size", "min_removal_count", "min_removal_set",
        ]
        for field in required:
            assert field in entry, (
                f"{history_name}: missing required field '{field}'"
            )


class TestCommittedCount:
    @pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
    def test_committed_count(self, results, history_name):
        expected = EXPECTED[history_name]["committed_count"]
        actual = results[history_name]["committed_count"]
        assert actual == expected, (
            f"{history_name}: expected committed_count={expected}, got {actual}"
        )


class TestConsistencyLevel:
    @pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
    def test_consistency_level(self, results, history_name):
        expected = EXPECTED[history_name]["consistency_level"]
        actual = results[history_name]["consistency_level"]
        assert actual == expected, (
            f"{history_name}: expected consistency_level='{expected}', got '{actual}'"
        )


class TestAnomalyFlags:
    @pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
    def test_g0(self, results, history_name):
        expected = EXPECTED[history_name]["g0"]
        actual = results[history_name]["g0"]
        assert actual == expected, (
            f"{history_name}: expected g0={expected}, got {actual}"
        )

    @pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
    def test_g1c(self, results, history_name):
        expected = EXPECTED[history_name]["g1c"]
        actual = results[history_name]["g1c"]
        assert actual == expected, (
            f"{history_name}: expected g1c={expected}, got {actual}"
        )

    @pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
    def test_g2(self, results, history_name):
        expected = EXPECTED[history_name]["g2"]
        actual = results[history_name]["g2"]
        assert actual == expected, (
            f"{history_name}: expected g2={expected}, got {actual}"
        )

    @pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
    def test_strict_serializable(self, results, history_name):
        expected = EXPECTED[history_name]["strict_serializable"]
        actual = results[history_name]["strict_serializable"]
        assert actual == expected, (
            f"{history_name}: expected strict_serializable={expected}, got {actual}"
        )


class TestEdgeCounts:
    @pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
    def test_ww_count(self, results, history_name):
        expected = EXPECTED[history_name]["edge_counts"]["ww"]
        actual = results[history_name]["edge_counts"]["ww"]
        assert actual == expected, (
            f"{history_name}: expected ww edge count={expected}, got {actual}"
        )

    @pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
    def test_wr_count(self, results, history_name):
        expected = EXPECTED[history_name]["edge_counts"]["wr"]
        actual = results[history_name]["edge_counts"]["wr"]
        assert actual == expected, (
            f"{history_name}: expected wr edge count={expected}, got {actual}"
        )

    @pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
    def test_rw_count(self, results, history_name):
        expected = EXPECTED[history_name]["edge_counts"]["rw"]
        actual = results[history_name]["edge_counts"]["rw"]
        assert actual == expected, (
            f"{history_name}: expected rw edge count={expected}, got {actual}"
        )


class TestShortestCycle:
    @pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
    def test_shortest_cycle(self, results, history_name):
        expected = EXPECTED[history_name]["shortest_cycle"]
        actual = results[history_name]["shortest_cycle"]
        assert actual == expected, (
            f"{history_name}: expected shortest_cycle={expected}, got {actual}"
        )


class TestSCCAnalysis:
    @pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
    def test_scc_count(self, results, history_name):
        expected = EXPECTED[history_name]["scc_count"]
        actual = results[history_name]["scc_count"]
        assert actual == expected, (
            f"{history_name}: expected scc_count={expected}, got {actual}"
        )

    @pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
    def test_scc_max_size(self, results, history_name):
        expected = EXPECTED[history_name]["scc_max_size"]
        actual = results[history_name]["scc_max_size"]
        assert actual == expected, (
            f"{history_name}: expected scc_max_size={expected}, got {actual}"
        )


class TestMinRemoval:
    @pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
    def test_min_removal_count(self, results, history_name):
        expected = EXPECTED[history_name]["min_removal_count"]
        actual = results[history_name]["min_removal_count"]
        assert actual == expected, (
            f"{history_name}: expected min_removal_count={expected}, got {actual}"
        )

    @pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
    def test_min_removal_set(self, results, history_name):
        expected = EXPECTED[history_name]["min_removal_set"]
        actual = results[history_name]["min_removal_set"]
        assert sorted(actual) == sorted(expected), (
            f"{history_name}: expected min_removal_set={expected}, got {actual}"
        )


class TestGraphVisualizations:
    @pytest.mark.parametrize("history_name", ANOMALOUS_HISTORIES)
    def test_svg_exists_for_anomalous(self, history_name):
        svg_path = f"/app/graphs/{history_name}.svg"
        assert os.path.exists(svg_path), (
            f"Missing SVG graph for anomalous history '{history_name}' "
            f"at {svg_path}. Anomalous histories must have a graphviz "
            f"visualization showing the dependency cycle."
        )

    @pytest.mark.parametrize("history_name", ANOMALOUS_HISTORIES)
    def test_svg_non_empty(self, history_name):
        svg_path = f"/app/graphs/{history_name}.svg"
        if os.path.exists(svg_path):
            size = os.path.getsize(svg_path)
            assert size > 100, (
                f"SVG file for '{history_name}' is suspiciously small "
                f"({size} bytes), likely not a valid visualization"
            )

    @pytest.mark.parametrize("history_name", ANOMALOUS_HISTORIES)
    def test_svg_contains_svg_element(self, history_name):
        svg_path = f"/app/graphs/{history_name}.svg"
        if os.path.exists(svg_path):
            with open(svg_path) as f:
                content = f.read()
            assert "<svg" in content.lower(), (
                f"SVG file for '{history_name}' does not contain <svg> element"
            )
