"""
Tests for the reproducibility evaluation reconciliation task.

"""

import json
import math
import os
import sqlite3

import pytest
import numpy as np
from scipy.stats import t as t_dist


SUMMARY_PATH = "/app/results/evaluation_summary.json"
INTERVALS_PATH = "/app/results/prediction_intervals.json"
AUDIT_PATH = "/app/results/sensitivity_audit.json"
GT_DB_PATH = "/app/ground_truth.db"


# ---- Helpers ----

def load_json(path):
    with open(path) as f:
        return json.load(f)


def compute_expected_pi(values):
    """Compute the correct 95% prediction interval for a list of values."""
    n = len(values)
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1))
    if std == 0.0:
        return (mean, mean)
    t_val = t_dist.ppf(0.975, n - 1)
    margin = t_val * std * math.sqrt(1.0 + 1.0 / n)
    return (mean - margin, mean + margin)


def compute_expected_ci(values):
    """Compute the correct 95% confidence interval for a list of values."""
    n = len(values)
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1))
    if std == 0.0:
        return (mean, mean)
    t_val = t_dist.ppf(0.975, n - 1)
    margin = t_val * std * math.sqrt(1.0 / n)
    return (mean - margin, mean + margin)


def get_capsule_ids_from_db():
    """Query SQLite database for all capsule IDs."""
    conn = sqlite3.connect(GT_DB_PATH)
    cursor = conn.execute("SELECT capsule_id FROM capsules ORDER BY capsule_id")
    ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return ids


# ---- Tests: Output files exist ----

class TestOutputFilesExist:
    def test_summary_exists(self):
        assert os.path.exists(SUMMARY_PATH), (
            f"evaluation_summary.json not found at {SUMMARY_PATH}"
        )

    def test_intervals_exists(self):
        assert os.path.exists(INTERVALS_PATH), (
            f"prediction_intervals.json not found at {INTERVALS_PATH}"
        )

    def test_audit_exists(self):
        assert os.path.exists(AUDIT_PATH), (
            f"sensitivity_audit.json not found at {AUDIT_PATH}"
        )


# ---- Tests: Prediction Intervals ----

class TestPredictionIntervals:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.intervals = load_json(INTERVALS_PATH)

    def test_capsule_8523_f1_score_bounds(self):
        """PI for f1_score must use t(0.975, 3) and sqrt(1+1/4), not CI formula."""
        pi = self.intervals["capsule-8523"]["f1_score"]
        expected = compute_expected_pi([0.891, 0.903, 0.897, 0.885])
        assert pi[0] == pytest.approx(expected[0], abs=0.001)
        assert pi[1] == pytest.approx(expected[1], abs=0.001)

    def test_capsule_5610_train_loss_contains_boundary_value(self):
        """Value 0.062 falls inside PI but outside CI; tests sqrt(1+1/n) factor."""
        pi = self.intervals["capsule-5610"]["train_loss"]
        assert pi[0] < 0.062 < pi[1], (
            f"train_loss PI [{pi[0]}, {pi[1]}] should contain 0.062 "
            "(only true with prediction interval, not confidence interval)"
        )

    def test_capsule_5610_val_auc_contains_boundary_value(self):
        """Value 0.925 falls inside PI but outside CI."""
        pi = self.intervals["capsule-5610"]["val_auc"]
        assert pi[0] < 0.925 < pi[1], (
            f"val_auc PI [{pi[0]}, {pi[1]}] should contain 0.925"
        )

    def test_capsule_3429_zero_variance(self):
        """When all runs are identical (std=0), PI collapses to [mean, mean]."""
        pi = self.intervals["capsule-3429"]["convergence_rate"]
        assert pi[0] == pytest.approx(45.2, abs=1e-6)
        assert pi[1] == pytest.approx(45.2, abs=1e-6)

    def test_capsule_6038_accuracy_bounds(self):
        """Standard 3-run PI with t(0.975, 2)."""
        pi = self.intervals["capsule-6038"]["accuracy"]
        expected = compute_expected_pi([0.85, 0.87, 0.86])
        assert pi[0] == pytest.approx(expected[0], abs=0.001)
        assert pi[1] == pytest.approx(expected[1], abs=0.001)

    def test_capsule_7291_rmse_bounds(self):
        """5-run PI with t(0.975, 4)."""
        pi = self.intervals["capsule-7291"]["rmse"]
        expected = compute_expected_pi([2.34, 2.56, 2.41, 2.38, 2.51])
        assert pi[0] == pytest.approx(expected[0], abs=0.001)
        assert pi[1] == pytest.approx(expected[1], abs=0.001)

    def test_all_capsules_have_intervals(self):
        """Every capsule in the ground truth database must have an entry."""
        capsule_ids = get_capsule_ids_from_db()
        for cid in capsule_ids:
            assert cid in self.intervals, f"Missing intervals for {cid}"


# ---- Tests: Agent 1 (all correct) ----

class TestAgent1:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.summary = load_json(SUMMARY_PATH)
        self.a1 = self.summary["agents"]["agent_1"]["summary"]
        self.capsules = self.summary["agents"]["agent_1"]["capsule_results"]

    def test_perfect_task_score(self):
        assert self.a1["correct_tasks"] == 8
        assert self.a1["total_tasks"] == 8

    def test_perfect_question_score(self):
        assert self.a1["correct_questions"] == 21
        assert self.a1["total_questions"] == 21

    def test_written_scores(self):
        assert self.a1["correct_written_questions"] == 17
        assert self.a1["total_written_questions"] == 17
        assert self.a1["correct_written_tasks"] == 8
        assert self.a1["total_written_tasks"] == 8

    def test_vision_scores(self):
        assert self.a1["correct_vision_questions"] == 4
        assert self.a1["total_vision_questions"] == 4
        assert self.a1["correct_vision_tasks"] == 4
        assert self.a1["total_vision_tasks"] == 4

    def test_percentage_handling_capsule_3429(self):
        """Agent 1 reports '45.2%' for convergence_rate; must be coerced to 45.2."""
        c3429 = [c for c in self.capsules if c["capsule_id"] == "capsule-3429"][0]
        assert c3429["correct_written"] == 1, (
            "convergence_rate '45.2%' should be coerced to 45.2 and match"
        )

    def test_case_insensitive_capsule_6038(self):
        """Agent 1 reports 'randomforest'; must match 'RandomForest' case-insensitively."""
        c6038 = [c for c in self.capsules if c["capsule_id"] == "capsule-6038"][0]
        assert c6038["correct_written"] == 3, (
            "best_model 'randomforest' should match 'RandomForest' case-insensitively"
        )


# ---- Tests: Agent 2 (partial scores) ----

class TestAgent2:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.summary = load_json(SUMMARY_PATH)
        self.a2 = self.summary["agents"]["agent_2"]["summary"]
        self.capsules = self.summary["agents"]["agent_2"]["capsule_results"]

    def test_correct_tasks(self):
        assert self.a2["correct_tasks"] == 2

    def test_written_question_count(self):
        assert self.a2["correct_written_questions"] == 11

    def test_vision_question_count(self):
        assert self.a2["correct_vision_questions"] == 1

    def test_correct_written_tasks(self):
        assert self.a2["correct_written_tasks"] == 5

    def test_correct_vision_tasks(self):
        assert self.a2["correct_vision_tasks"] == 1

    def test_capsule_8523_boundary(self):
        """f1_score=0.870 is inside PI but outside CI; must be correct under PI."""
        c8523 = [c for c in self.capsules if c["capsule_id"] == "capsule-8523"][0]
        assert c8523["correct_written"] == 1

    def test_capsule_5610_boundary(self):
        """train_loss=0.062 and val_auc=0.925 are inside PI but outside CI."""
        c5610 = [c for c in self.capsules if c["capsule_id"] == "capsule-5610"][0]
        assert c5610["correct_written"] == 2

    def test_capsule_2847_vision_classification(self):
        """confusion_matrix_fig has 'fig' in key (not at start); must be vision."""
        c2847 = [c for c in self.capsules if c["capsule_id"] == "capsule-2847"][0]
        assert c2847["total_written"] == 2, (
            "sensitivity and specificity are written; confusion_matrix_fig is vision"
        )
        assert c2847["total_vision"] == 1, (
            "confusion_matrix_fig contains 'fig' so it must be classified as vision"
        )


# ---- Tests: Agent 3 (zero scores) ----

class TestAgent3:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.summary = load_json(SUMMARY_PATH)
        self.a3 = self.summary["agents"]["agent_3"]["summary"]

    def test_zero_tasks(self):
        assert self.a3["correct_tasks"] == 0

    def test_zero_questions(self):
        assert self.a3["correct_questions"] == 0

    def test_total_counts_consistent(self):
        assert self.a3["total_tasks"] == 8
        assert self.a3["total_questions"] == 21
        assert self.a3["total_written_questions"] == 17
        assert self.a3["total_vision_questions"] == 4


# ---- Tests: Structural ----

class TestStructure:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.summary = load_json(SUMMARY_PATH)

    def test_all_agents_present(self):
        agents = self.summary["agents"]
        assert "agent_1" in agents
        assert "agent_2" in agents
        assert "agent_3" in agents

    def test_capsule_results_count(self):
        for agent_name in ["agent_1", "agent_2", "agent_3"]:
            capsules = self.summary["agents"][agent_name]["capsule_results"]
            assert len(capsules) == 8, f"{agent_name} should have 8 capsule results"

    def test_summary_keys(self):
        required_keys = {
            "correct_tasks", "total_tasks",
            "correct_questions", "total_questions",
            "correct_written_tasks", "total_written_tasks",
            "correct_vision_tasks", "total_vision_tasks",
            "correct_written_questions", "total_written_questions",
            "correct_vision_questions", "total_vision_questions",
        }
        for agent_name in ["agent_1", "agent_2", "agent_3"]:
            summary = self.summary["agents"][agent_name]["summary"]
            assert required_keys.issubset(set(summary.keys())), (
                f"{agent_name} summary missing keys: "
                f"{required_keys - set(summary.keys())}"
            )


# ---- Tests: Sensitivity Audit ----

class TestSensitivityAudit:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.audit = load_json(AUDIT_PATH)

    def test_has_required_sections(self):
        assert "method_comparison" in self.audit
        assert "fragile_results" in self.audit
        assert "robustness_scores" in self.audit

    def test_robustness_score_agent_1(self):
        """Agent 1 is perfect and all answers are within both PI and CI."""
        assert self.audit["robustness_scores"]["agent_1"] == pytest.approx(1.0, abs=0.01)

    def test_robustness_score_agent_2(self):
        """Agent 2 has 12 PI-correct answers, 3 fragile -> robustness = 9/12 = 0.75."""
        assert self.audit["robustness_scores"]["agent_2"] == pytest.approx(0.75, abs=0.01)

    def test_robustness_score_agent_3(self):
        """Agent 3 has 0 correct answers -> robustness = 1.0 (vacuously robust)."""
        assert self.audit["robustness_scores"]["agent_3"] == pytest.approx(1.0, abs=0.01)

    def test_fragile_count(self):
        """Exactly 3 fragile results: all cases where PI accepts but CI rejects."""
        assert len(self.audit["fragile_results"]) == 3

    def test_fragile_all_agent_2(self):
        """All fragile results belong to agent_2; agents 1 and 3 have none."""
        fragile_str = json.dumps(self.audit["fragile_results"])
        assert "agent_1" not in fragile_str, "agent_1 should have no fragile results"
        assert "agent_3" not in fragile_str, "agent_3 should have no fragile results"
        assert "agent_2" in fragile_str, "agent_2 should have fragile results"

    def test_fragile_expected_entries(self):
        """Fragile results must cover the three PI/CI boundary cases."""
        fragile_str = json.dumps(self.audit["fragile_results"])
        assert "capsule-8523" in fragile_str and "f1_score" in fragile_str, (
            "f1_score=0.870 on capsule-8523 is inside PI but outside CI"
        )
        assert "capsule-5610" in fragile_str and "train_loss" in fragile_str, (
            "train_loss=0.062 on capsule-5610 is inside PI but outside CI"
        )
        assert "val_auc" in fragile_str, (
            "val_auc=0.925 on capsule-5610 is inside PI but outside CI"
        )

    def test_method_comparison_has_both_intervals(self):
        """Method comparison must have both PI and CI for numeric keys."""
        mc = self.audit["method_comparison"]
        assert "capsule-8523" in mc
        f1_entry = mc["capsule-8523"]["f1_score"]
        assert "prediction_interval" in f1_entry
        assert "confidence_interval" in f1_entry

    def test_ci_bounds_capsule_5610_train_loss(self):
        """CI bounds must use sqrt(1/n) and be tighter than PI."""
        mc = self.audit["method_comparison"]["capsule-5610"]["train_loss"]
        ci = mc["confidence_interval"]
        pi = mc["prediction_interval"]
        expected_ci = compute_expected_ci([0.0460, 0.0538, 0.0503])
        assert ci[0] == pytest.approx(expected_ci[0], abs=0.001)
        assert ci[1] == pytest.approx(expected_ci[1], abs=0.001)
        # CI must be strictly tighter than PI
        assert ci[0] > pi[0], "CI lower bound should be above PI lower bound"
        assert ci[1] < pi[1], "CI upper bound should be below PI upper bound"

    def test_ci_bounds_capsule_8523_f1_score(self):
        """CI bounds for f1_score -- the value 0.870 should be outside CI."""
        mc = self.audit["method_comparison"]["capsule-8523"]["f1_score"]
        ci = mc["confidence_interval"]
        expected_ci = compute_expected_ci([0.891, 0.903, 0.897, 0.885])
        assert ci[0] == pytest.approx(expected_ci[0], abs=0.001)
        assert ci[1] == pytest.approx(expected_ci[1], abs=0.001)
        # 0.870 should be outside CI
        assert not (ci[0] <= 0.870 <= ci[1]), (
            "f1_score=0.870 should be OUTSIDE the CI bounds"
        )

    def test_ci_zero_variance_matches_pi(self):
        """For zero-variance capsules, CI and PI should be identical."""
        mc = self.audit["method_comparison"]["capsule-3429"]["convergence_rate"]
        ci = mc["confidence_interval"]
        pi = mc["prediction_interval"]
        assert ci[0] == pytest.approx(pi[0], abs=1e-6)
        assert ci[1] == pytest.approx(pi[1], abs=1e-6)
