
"""Tests for MIB evaluation pipeline forensics task."""

import json
import os
import math
import re
import sqlite3
import pytest

BUG_REPORT_PATH = "/app/bug_report.json"
RESULTS_PATH = "/app/corrected_results.json"
CONFIG_PATH = "/app/simulator_config.json"
DB_PATH = "/app/mib.db"
TOL = 1e-4

# Expected correct values (computed from deterministic simulator with correct algorithms)
EXPECTED = {
    "methods": {
        "eap": {
            "ioi": {
                "faithfulnesses": [
                    0.0, 0.0, 0.0, 0.0320201402, 0.071480101,
                    0.1842898389, 0.3516528681, 0.4699217463,
                    0.6461873637, 1.0054419197
                ],
                "weighted_edge_counts": [0, 0, 0, 64, 128, 576, 1218, 2437, 6472, 12561],
                "cpr": 0.6392350864,
                "cmd": 0.3624858734,
                "cpr_log": 1.718378557,
                "cmd_log": 5.1931487732
            },
            "mcqa": {
                "faithfulnesses": [
                    0.0, 0.0, 0.0, 0.0408490788, 0.0730109837,
                    0.1619041988, 0.3364273314, 0.4118526078,
                    0.5493161243, 1.0000302371
                ],
                "weighted_edge_counts": [0, 0, 0, 64, 128, 576, 1473, 2308, 6025, 12561],
                "cpr": 0.5855793361,
                "cmd": 0.4134357824,
                "cpr_log": 1.570603549,
                "cmd_log": 5.3371726888
            }
        },
        "eap_ig": {
            "ioi": {
                "faithfulnesses": [
                    0.0, 0.0, 0.0, 0.0168635567, 0.0284215167,
                    0.1513860572, 0.2893315169, 0.7006434042,
                    0.8689596149, 1.0054419197
                ],
                "weighted_edge_counts": [0, 0, 0, 1, 2, 450, 708, 1606, 5578, 12561],
                "cpr": 0.7675232198,
                "cmd": 0.2341977401,
                "cpr_log": 1.9684817343,
                "cmd_log": 4.9430455959
            },
            "mcqa": {
                "faithfulnesses": [
                    0.0, 0.0, 0.0, 0.0309053287, 0.057925234,
                    0.2056678445, 0.4085700852, 0.6881882108,
                    0.8625056127, 1.0000302371
                ],
                "weighted_edge_counts": [0, 0, 0, 1, 2, 387, 1155, 2116, 6025, 12561],
                "cpr": 0.7729072114,
                "cmd": 0.2261079072,
                "cpr_log": 2.1111962759,
                "cmd_log": 4.7965799619
            }
        },
        "act_patch": {
            "ioi": {
                "faithfulnesses": [
                    0.0, 0.0, 0.0, 0.0141426699, 0.0267137208,
                    0.092254506, 0.1366432236, 0.2598157291,
                    0.4449222193, 1.0054419197
                ],
                "weighted_edge_counts": [0, 0, 0, 64, 65, 258, 834, 2050, 6151, 12561],
                "cpr": 0.4958712799,
                "cmd": 0.5058496799,
                "cpr_log": 1.1158284065,
                "cmd_log": 5.7956989238
            },
            "mcqa": {
                "faithfulnesses": [
                    0.0, 0.0, 0.0, 0.0489785955, 0.0798839242,
                    0.2047117085, 0.2049999526, 0.3878370098,
                    0.4470475214, 1.0000302371
                ],
                "weighted_edge_counts": [0, 0, 0, 256, 257, 705, 1281, 2689, 6790, 12561],
                "cpr": 0.5319224526,
                "cmd": 0.467092666,
                "cpr_log": 1.4234954932,
                "cmd_log": 5.4842807446
            }
        }
    },
    "auroc": {
        "eap": {"ioi": 0.6522796353, "mcqa": 0.5750841751},
        "eap_ig": {"ioi": 0.894224924, "mcqa": 0.8383838384},
        "act_patch": {"ioi": 0.3696048632, "mcqa": 0.4750841751}
    },
    "ranking": {
        "by_cpr": ["eap_ig", "eap", "act_patch"],
        "by_cmd": ["eap_ig", "eap", "act_patch"]
    }
}


@pytest.fixture
def bug_report():
    """Load the agent's bug report."""
    assert os.path.exists(BUG_REPORT_PATH), \
        f"Bug report not found at {BUG_REPORT_PATH}"
    with open(BUG_REPORT_PATH, 'r') as f:
        return json.load(f)


@pytest.fixture
def results():
    """Load the agent's corrected results."""
    assert os.path.exists(RESULTS_PATH), \
        f"Corrected results not found at {RESULTS_PATH}"
    with open(RESULTS_PATH, 'r') as f:
        return json.load(f)


@pytest.fixture
def sim_config():
    """Load the reconstructed simulator config."""
    assert os.path.exists(CONFIG_PATH), \
        f"Simulator config not found at {CONFIG_PATH} — must be reconstructed from database"
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)


# =========================================================================
# Simulator config reconstruction tests
# =========================================================================

class TestSimulatorConfig:
    """Verify simulator_config.json was correctly reconstructed from the database."""

    def test_config_exists(self):
        assert os.path.exists(CONFIG_PATH), \
            "simulator_config.json must be reconstructed from the database"

    def test_config_has_all_tasks(self, sim_config):
        for task in ["ioi", "mcqa"]:
            assert task in sim_config, f"Missing task '{task}' in config"

    def test_config_task_keys(self, sim_config):
        for task in ["ioi", "mcqa"]:
            assert "baseline_score" in sim_config[task], \
                f"Missing baseline_score for {task}"
            assert "corrupted_score" in sim_config[task], \
                f"Missing corrupted_score for {task}"
            assert "ground_truth_weights" in sim_config[task], \
                f"Missing ground_truth_weights for {task}"

    def test_config_baseline_corrupted(self, sim_config):
        """Verify baseline/corrupted scores match database values."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            "SELECT task, baseline_score, corrupted_score FROM simulator_config"
        ):
            task = row["task"]
            assert abs(sim_config[task]["baseline_score"] - row["baseline_score"]) < 1e-8, \
                f"baseline_score mismatch for {task}"
            assert abs(sim_config[task]["corrupted_score"] - row["corrupted_score"]) < 1e-8, \
                f"corrupted_score mismatch for {task}"
        conn.close()

    def test_config_gt_weights(self, sim_config):
        """Verify ground truth weights match database values."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        db_weights = {}
        for row in conn.execute("SELECT task, edge_name, weight FROM gt_weights"):
            db_weights.setdefault(row["task"], {})[row["edge_name"]] = row["weight"]
        conn.close()

        for task in ["ioi", "mcqa"]:
            config_gt = sim_config[task]["ground_truth_weights"]
            assert len(config_gt) == len(db_weights[task]), \
                f"Ground truth weight count mismatch for {task}: " \
                f"config has {len(config_gt)}, DB has {len(db_weights[task])}"
            for edge, weight in db_weights[task].items():
                assert edge in config_gt, \
                    f"Missing edge {edge} in config ground_truth_weights for {task}"
                assert abs(config_gt[edge] - weight) < 1e-8, \
                    f"Weight mismatch for {edge} in {task}"

    def test_config_gt_weight_range(self, sim_config):
        """Verify ground truth weights are in expected range."""
        for task in ["ioi", "mcqa"]:
            for edge, weight in sim_config[task]["ground_truth_weights"].items():
                assert 0.3 <= weight <= 2.5, \
                    f"Weight {weight} for {edge} in {task} out of expected range"


# =========================================================================
# Bug report tests
# =========================================================================

class TestBugReportStructure:
    """Verify bug_report.json structure."""

    def test_has_bugs_key(self, bug_report):
        assert "bugs" in bug_report, "bug_report.json must have 'bugs' key"

    def test_at_least_four_bugs(self, bug_report):
        assert len(bug_report["bugs"]) >= 4, \
            f"Expected at least 4 bugs, found {len(bug_report['bugs'])}"

    def test_each_entry_has_required_keys(self, bug_report):
        for i, bug in enumerate(bug_report["bugs"]):
            assert "location" in bug, f"Bug {i} missing 'location'"
            assert "description" in bug, f"Bug {i} missing 'description'"
            assert "fix" in bug, f"Bug {i} missing 'fix'"

    def test_descriptions_are_meaningful(self, bug_report):
        for i, bug in enumerate(bug_report["bugs"]):
            assert len(bug["description"]) >= 20, \
                f"Bug {i} description too short: '{bug['description'][:30]}'"
            assert len(bug["fix"]) >= 10, \
                f"Bug {i} fix too short: '{bug['fix'][:30]}'"


class TestBugIdentification:
    """Verify each specific bug is identified in the report."""

    def _all_texts(self, bug_report):
        return [
            f"{b.get('location', '')} {b['description']} {b['fix']}".lower()
            for b in bug_report["bugs"]
        ]

    def test_abs_bug_identified(self, bug_report):
        """Bug: Missing abs() in edge ranking — ranks by raw score not magnitude."""
        texts = self._all_texts(bug_report)
        found = any(
            "abs" in t or "absolute" in t or "magnitude" in t or "|score|" in t
            for t in texts
        )
        assert found, \
            "Bug report must identify missing abs()/absolute-value in edge ranking"

    def test_normalization_bug_identified(self, bug_report):
        """Bug: Inverted faithfulness normalization formula."""
        texts = self._all_texts(bug_report)
        found = any(
            "invert" in t or "normali" in t or "numerator" in t or
            "direction" in t or "swap" in t or "flip" in t or
            ("baseline" in t and "raw" in t) or
            "subtraction" in t
            for t in texts
        )
        assert found, \
            "Bug report must identify inverted faithfulness normalization"

    def test_round_bug_identified(self, bug_report):
        """Bug: Uses round() instead of floor() for edge count k."""
        texts = self._all_texts(bug_report)
        found = any(
            "round" in t or "floor" in t or "int(" in t or "truncat" in t
            for t in texts
        )
        assert found, \
            "Bug report must identify round() vs floor() issue"

    def test_log_bug_identified(self, bug_report):
        """Bug: Uses log10 instead of natural log for log-scale metrics."""
        texts = self._all_texts(bug_report)
        found = any(
            "log10" in t or "log_10" in t or "natural" in t or
            " ln " in t or " ln(" in t or "math.log(" in t or
            "logarithm" in t
            for t in texts
        )
        assert found, \
            "Bug report must identify log10 vs natural log issue"


# =========================================================================
# Corrected results — structure tests
# =========================================================================

class TestResultsStructure:
    """Verify corrected_results.json has the required structure."""

    def test_top_level_keys(self, results):
        assert "methods" in results, "Missing 'methods' key"
        assert "auroc" in results, "Missing 'auroc' key"
        assert "ranking" in results, "Missing 'ranking' key"

    def test_methods_keys(self, results):
        for method in ["eap", "eap_ig", "act_patch"]:
            assert method in results["methods"], f"Missing method '{method}'"
            for task in ["ioi", "mcqa"]:
                assert task in results["methods"][method], \
                    f"Missing task '{task}' for method '{method}'"

    def test_method_task_keys(self, results):
        for method in ["eap", "eap_ig", "act_patch"]:
            for task in ["ioi", "mcqa"]:
                entry = results["methods"][method][task]
                for key in ["faithfulnesses", "weighted_edge_counts",
                            "cpr", "cmd", "cpr_log", "cmd_log"]:
                    assert key in entry, \
                        f"Missing key '{key}' for {method}/{task}"

    def test_faithfulness_length(self, results):
        for method in ["eap", "eap_ig", "act_patch"]:
            for task in ["ioi", "mcqa"]:
                f = results["methods"][method][task]["faithfulnesses"]
                assert len(f) == 10, \
                    f"Expected 10 faithfulness values for {method}/{task}"

    def test_wec_length(self, results):
        for method in ["eap", "eap_ig", "act_patch"]:
            for task in ["ioi", "mcqa"]:
                w = results["methods"][method][task]["weighted_edge_counts"]
                assert len(w) == 10, \
                    f"Expected 10 WEC values for {method}/{task}"

    def test_ranking_keys(self, results):
        assert "by_cpr" in results["ranking"]
        assert "by_cmd" in results["ranking"]
        assert len(results["ranking"]["by_cpr"]) == 3
        assert len(results["ranking"]["by_cmd"]) == 3


# =========================================================================
# Corrected results — faithfulness tests
# =========================================================================

class TestFaithfulness:
    """Verify faithfulness values match expected."""

    @pytest.mark.parametrize("method", ["eap", "eap_ig", "act_patch"])
    @pytest.mark.parametrize("task", ["ioi", "mcqa"])
    def test_faithfulness_values(self, results, method, task):
        actual = results["methods"][method][task]["faithfulnesses"]
        expected = EXPECTED["methods"][method][task]["faithfulnesses"]
        for i, (a, e) in enumerate(zip(actual, expected)):
            assert abs(a - e) < TOL, \
                f"Faithfulness mismatch at index {i} for {method}/{task}: " \
                f"got {a}, expected {e} (diff={abs(a-e):.2e})"

    @pytest.mark.parametrize("method", ["eap", "eap_ig", "act_patch"])
    @pytest.mark.parametrize("task", ["ioi", "mcqa"])
    def test_zero_edges_faithfulness(self, results, method, task):
        f = results["methods"][method][task]["faithfulnesses"]
        assert f[0] == 0.0, f"f[0] should be 0 for {method}/{task}"
        assert f[1] == 0.0, f"f[1] should be 0 for {method}/{task}"
        assert f[2] == 0.0, f"f[2] should be 0 for {method}/{task}"


# =========================================================================
# Corrected results — weighted edge counts
# =========================================================================

class TestWeightedEdgeCounts:

    @pytest.mark.parametrize("method", ["eap", "eap_ig", "act_patch"])
    @pytest.mark.parametrize("task", ["ioi", "mcqa"])
    def test_wec_values(self, results, method, task):
        actual = results["methods"][method][task]["weighted_edge_counts"]
        expected = EXPECTED["methods"][method][task]["weighted_edge_counts"]
        for i, (a, e) in enumerate(zip(actual, expected)):
            assert a == e, \
                f"WEC mismatch at index {i} for {method}/{task}: " \
                f"got {a}, expected {e}"


# =========================================================================
# Corrected results — CPR / CMD
# =========================================================================

class TestCPR:

    @pytest.mark.parametrize("method", ["eap", "eap_ig", "act_patch"])
    @pytest.mark.parametrize("task", ["ioi", "mcqa"])
    def test_cpr_linear(self, results, method, task):
        actual = results["methods"][method][task]["cpr"]
        expected = EXPECTED["methods"][method][task]["cpr"]
        assert abs(actual - expected) < TOL, \
            f"CPR mismatch for {method}/{task}: {actual} vs {expected}"

    @pytest.mark.parametrize("method", ["eap", "eap_ig", "act_patch"])
    @pytest.mark.parametrize("task", ["ioi", "mcqa"])
    def test_cpr_log(self, results, method, task):
        actual = results["methods"][method][task]["cpr_log"]
        expected = EXPECTED["methods"][method][task]["cpr_log"]
        assert abs(actual - expected) < TOL, \
            f"CPR_log mismatch for {method}/{task}: {actual} vs {expected}"


class TestCMD:

    @pytest.mark.parametrize("method", ["eap", "eap_ig", "act_patch"])
    @pytest.mark.parametrize("task", ["ioi", "mcqa"])
    def test_cmd_linear(self, results, method, task):
        actual = results["methods"][method][task]["cmd"]
        expected = EXPECTED["methods"][method][task]["cmd"]
        assert abs(actual - expected) < TOL, \
            f"CMD mismatch for {method}/{task}: {actual} vs {expected}"

    @pytest.mark.parametrize("method", ["eap", "eap_ig", "act_patch"])
    @pytest.mark.parametrize("task", ["ioi", "mcqa"])
    def test_cmd_log(self, results, method, task):
        actual = results["methods"][method][task]["cmd_log"]
        expected = EXPECTED["methods"][method][task]["cmd_log"]
        assert abs(actual - expected) < TOL, \
            f"CMD_log mismatch for {method}/{task}: {actual} vs {expected}"


# =========================================================================
# Corrected results — AUROC
# =========================================================================

class TestAUROC:

    @pytest.mark.parametrize("method", ["eap", "eap_ig", "act_patch"])
    @pytest.mark.parametrize("task", ["ioi", "mcqa"])
    def test_auroc(self, results, method, task):
        actual = results["auroc"][method][task]
        expected = EXPECTED["auroc"][method][task]
        assert abs(actual - expected) < TOL, \
            f"AUROC mismatch for {method}/{task}: {actual} vs {expected}"

    def test_auroc_range(self, results):
        for method in ["eap", "eap_ig", "act_patch"]:
            for task in ["ioi", "mcqa"]:
                v = results["auroc"][method][task]
                assert 0.0 <= v <= 1.0, \
                    f"AUROC out of range for {method}/{task}: {v}"

    def test_eap_ig_best_auroc(self, results):
        for task in ["ioi", "mcqa"]:
            eap_ig = results["auroc"]["eap_ig"][task]
            for method in ["eap", "act_patch"]:
                assert eap_ig > results["auroc"][method][task], \
                    f"eap_ig should have higher AUROC than {method} on {task}"


# =========================================================================
# Corrected results — Rankings
# =========================================================================

class TestRanking:

    def test_ranking_by_cpr(self, results):
        expected = EXPECTED["ranking"]["by_cpr"]
        actual = results["ranking"]["by_cpr"]
        assert actual == expected, \
            f"CPR ranking mismatch: got {actual}, expected {expected}"

    def test_ranking_by_cmd(self, results):
        expected = EXPECTED["ranking"]["by_cmd"]
        actual = results["ranking"]["by_cmd"]
        assert actual == expected, \
            f"CMD ranking mismatch: got {actual}, expected {expected}"


# =========================================================================
# Cross-metric consistency checks
# =========================================================================

class TestConsistency:

    def test_cpr_cmd_sum(self, results):
        for method in ["eap", "eap_ig", "act_patch"]:
            for task in ["ioi", "mcqa"]:
                cpr = results["methods"][method][task]["cpr"]
                cmd = results["methods"][method][task]["cmd"]
                total = cpr + cmd
                assert 0.95 <= total <= 1.05, \
                    f"CPR+CMD={total} out of expected range for {method}/{task}"

    def test_full_circuit_faithfulness(self, results):
        for method in ["eap", "eap_ig", "act_patch"]:
            for task in ["ioi", "mcqa"]:
                f_100 = results["methods"][method][task]["faithfulnesses"][-1]
                assert abs(f_100 - 1.0) < 0.02, \
                    f"Full circuit faithfulness should be ~1.0, got {f_100}"

    def test_monotonic_trend(self, results):
        for method in ["eap", "eap_ig", "act_patch"]:
            for task in ["ioi", "mcqa"]:
                f = results["methods"][method][task]["faithfulnesses"]
                non_zero = [v for v in f if v > 0]
                if len(non_zero) >= 2:
                    assert non_zero[-1] > non_zero[0], \
                        f"Faithfulness should increase overall for {method}/{task}"
