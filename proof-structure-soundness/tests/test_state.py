
import json
import os
import pytest


@pytest.fixture
def report():
    path = "/app/audit_report.json"
    assert os.path.isfile(path), f"Output file {path} does not exist"
    with open(path) as f:
        data = json.load(f)
    return data


class TestOverallSoundness:
    def test_overall_sound_is_false(self, report):
        assert "overall_sound" in report, "Missing 'overall_sound' key"
        assert report["overall_sound"] is False, "overall_sound should be False"


class TestCircularDependencies:
    def test_circular_dependencies_key_exists(self, report):
        assert "circular_dependencies" in report, "Missing 'circular_dependencies' key"

    def test_exactly_three_cycles(self, report):
        cycles = report["circular_dependencies"]
        assert isinstance(cycles, list), "circular_dependencies must be a list"
        assert len(cycles) == 3, (
            f"Expected exactly 3 circular dependency cycles, got {len(cycles)}: "
            f"{[c.get('cycle', c) for c in cycles]}"
        )

    def test_transitive_cycle_p1_p2_p3(self, report):
        cycles = report["circular_dependencies"]
        cycle_sets = [frozenset(c["cycle"]) for c in cycles]
        expected = frozenset(["P1", "P2", "P3"])
        assert expected in cycle_sets, (
            f"Missing transitive cycle {{P1, P2, P3}}. Found cycles: {cycle_sets}"
        )

    def test_direct_cycle_p4a_p4b(self, report):
        cycles = report["circular_dependencies"]
        cycle_sets = [frozenset(c["cycle"]) for c in cycles]
        expected = frozenset(["P4a", "P4b"])
        assert expected in cycle_sets, (
            f"Missing direct cycle {{P4a, P4b}}. Found cycles: {cycle_sets}"
        )

    def test_direct_cycle_p7_p8(self, report):
        cycles = report["circular_dependencies"]
        cycle_sets = [frozenset(c["cycle"]) for c in cycles]
        expected = frozenset(["P7", "P8"])
        assert expected in cycle_sets, (
            f"Missing direct cycle {{P7, P8}}. Found cycles: {cycle_sets}"
        )

    def test_cycles_are_sorted(self, report):
        cycles = report["circular_dependencies"]
        for entry in cycles:
            cycle = entry["cycle"]
            assert cycle == sorted(cycle), (
                f"Cycle {cycle} is not sorted alphabetically"
            )


class TestIncompleteCaseSplits:
    def test_key_exists(self, report):
        assert "incomplete_case_splits" in report, (
            "Missing 'incomplete_case_splits' key"
        )

    def test_exactly_two_incomplete_splits(self, report):
        issues = report["incomplete_case_splits"]
        assert isinstance(issues, list), "incomplete_case_splits must be a list"
        assert len(issues) == 2, (
            f"Expected exactly 2 incomplete case-splits, got {len(issues)}: "
            f"{[i.get('node_id', i) for i in issues]}"
        )

    def test_p1_missing_rmw_and_burst(self, report):
        issues = report["incomplete_case_splits"]
        p1_issues = [i for i in issues if i.get("node_id") == "P1"]
        assert len(p1_issues) == 1, "Expected one incomplete case-split entry for P1"
        p1 = p1_issues[0]
        assert p1["signal"] == "access_type", (
            f"P1 split signal should be 'access_type', got '{p1['signal']}'"
        )
        assert set(p1["missing"]) == {"RMW", "BURST"}, (
            f"P1 missing values should be {{RMW, BURST}}, got {p1['missing']}"
        )
        assert set(p1["covered"]) == {"READ", "WRITE"}, (
            f"P1 covered values should be {{READ, WRITE}}, got {p1['covered']}"
        )

    def test_p7_missing_fatal(self, report):
        issues = report["incomplete_case_splits"]
        p7_issues = [i for i in issues if i.get("node_id") == "P7"]
        assert len(p7_issues) == 1, "Expected one incomplete case-split entry for P7"
        p7 = p7_issues[0]
        assert p7["signal"] == "error_class", (
            f"P7 split signal should be 'error_class', got '{p7['signal']}'"
        )
        assert set(p7["missing"]) == {"fatal"}, (
            f"P7 missing values should be {{fatal}}, got {p7['missing']}"
        )
        assert set(p7["covered"]) == {"correctable", "uncorrectable"}, (
            f"P7 covered values should be {{correctable, uncorrectable}}, got {p7['covered']}"
        )

    def test_missing_values_sorted(self, report):
        issues = report["incomplete_case_splits"]
        for issue in issues:
            missing = issue["missing"]
            assert missing == sorted(missing), (
                f"Missing values {missing} for {issue['node_id']} not sorted"
            )


class TestDecompositionSoundness:
    def test_key_exists(self, report):
        assert "decomposition_soundness" in report, (
            "Missing 'decomposition_soundness' key"
        )

    def test_all_nonleaf_nodes_present(self, report):
        ds = report["decomposition_soundness"]
        expected_nodes = {"P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"}
        actual_nodes = set(ds.keys())
        missing = expected_nodes - actual_nodes
        assert not missing, f"Missing non-leaf nodes in decomposition_soundness: {missing}"

    def test_p0_unsound(self, report):
        ds = report["decomposition_soundness"]
        assert ds["P0"] is False, "P0 should be unsound (cycles among children + unsound children)"

    def test_p1_unsound(self, report):
        ds = report["decomposition_soundness"]
        assert ds["P1"] is False, "P1 should be unsound (incomplete case-split: missing RMW, BURST)"

    def test_p2_sound(self, report):
        ds = report["decomposition_soundness"]
        assert ds["P2"] is True, "P2 should be sound (partition complete, all children proven)"

    def test_p3_sound(self, report):
        ds = report["decomposition_soundness"]
        assert ds["P3"] is True, "P3 should be sound (case-split complete, all children proven)"

    def test_p4_unsound(self, report):
        ds = report["decomposition_soundness"]
        assert ds["P4"] is False, "P4 should be unsound (cycle between P4a and P4b)"

    def test_p5_sound(self, report):
        ds = report["decomposition_soundness"]
        assert ds["P5"] is True, "P5 should be sound (stopat with proven child)"

    def test_p6_sound(self, report):
        ds = report["decomposition_soundness"]
        assert ds["P6"] is True, "P6 should be sound (complete case-split over power_state)"

    def test_p7_unsound(self, report):
        ds = report["decomposition_soundness"]
        assert ds["P7"] is False, "P7 should be unsound (incomplete case-split: missing 'fatal')"

    def test_p8_sound(self, report):
        ds = report["decomposition_soundness"]
        assert ds["P8"] is True, (
            "P8 should be sound (no cycle among its own children P8a/P8b, "
            "even though P8 is in a P0-level cycle with P7)"
        )

    def test_no_leaf_nodes_in_soundness(self, report):
        ds = report["decomposition_soundness"]
        leaf_ids = {"P1a", "P1b", "P2a", "P2b", "P2c", "P3a", "P3b",
                    "P4a", "P4b", "P5a", "P6a", "P6b", "P6c", "P6d",
                    "P7a", "P7b", "P8a", "P8b"}
        found_leaves = leaf_ids & set(ds.keys())
        assert not found_leaves, (
            f"Leaf nodes should not appear in decomposition_soundness: {found_leaves}"
        )


class TestOutputFormat:
    def test_valid_json(self):
        path = "/app/audit_report.json"
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict), "Output must be a JSON object"

    def test_required_top_level_keys(self, report):
        required = {"overall_sound", "circular_dependencies",
                     "incomplete_case_splits", "decomposition_soundness"}
        actual = set(report.keys())
        missing = required - actual
        assert not missing, f"Missing required top-level keys: {missing}"
