
import json
import math
import sqlite3

import numpy as np
import pytest
from scipy.stats import t as t_dist

REPORT_PATH = "/app/evaluation_report.json"
METHODOLOGY_PATH = "/app/methodology.json"
DB_PATH = "/app/capsules.db"


@pytest.fixture
def report():
    with open(REPORT_PATH) as f:
        return json.load(f)


@pytest.fixture
def ground_truth():
    """Extract ground truth directly from SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    capsules = c.execute(
        'SELECT capsule_id FROM capsules ORDER BY rowid'
    ).fetchall()
    result = []
    for (cap_id,) in capsules:
        runs = c.execute(
            'SELECT run_number FROM runs WHERE capsule_id=? ORDER BY run_number',
            (cap_id,)
        ).fetchall()
        results_list = []
        for (run_num,) in runs:
            run_data = {}
            for row in c.execute(
                'SELECT metric, value FROM numeric_results '
                'WHERE capsule_id=? AND run_number=?', (cap_id, run_num)
            ):
                run_data[row[0]] = row[1]
            for row in c.execute(
                'SELECT metric, value FROM string_results '
                'WHERE capsule_id=? AND run_number=?', (cap_id, run_num)
            ):
                run_data[row[0]] = row[1]
            results_list.append(run_data)
        result.append({'capsule_id': cap_id, 'results': results_list})
    conn.close()
    return result


class TestReportStructure:
    def test_top_level_keys(self, report):
        assert "agent_evaluations" in report
        assert "rankings" in report

    def test_all_agents_present(self, report):
        agents = report["agent_evaluations"]
        assert "agent_alpha" in agents
        assert "agent_beta" in agents
        assert "agent_gamma" in agents

    def test_agent_has_required_fields(self, report):
        for agent_name, agent_data in report["agent_evaluations"].items():
            assert "capsule_results" in agent_data, f"{agent_name} missing capsule_results"
            assert "summary" in agent_data, f"{agent_name} missing summary"
            assert len(agent_data["capsule_results"]) == 8, (
                f"{agent_name} has {len(agent_data['capsule_results'])} capsules, expected 8"
            )

    def test_summary_keys(self, report):
        expected_keys = {
            "correct_tasks", "total_tasks", "correct_questions", "total_questions",
            "correct_written_tasks", "total_written_tasks",
            "correct_vision_tasks", "total_vision_tasks",
            "correct_written_questions", "total_written_questions",
            "correct_vision_questions", "total_vision_questions",
        }
        for agent_name, agent_data in report["agent_evaluations"].items():
            assert set(agent_data["summary"].keys()) >= expected_keys, (
                f"{agent_name} summary missing keys"
            )

    def test_capsule_result_keys(self, report):
        required = {"capsule_id", "correct_written_answers", "correct_vision_answers",
                     "total_written_questions", "total_vision_questions"}
        for agent_name, agent_data in report["agent_evaluations"].items():
            for cr in agent_data["capsule_results"]:
                assert set(cr.keys()) >= required, (
                    f"{agent_name} capsule {cr.get('capsule_id')} missing keys"
                )


class TestAgentAlpha:
    def test_correct_tasks(self, report):
        s = report["agent_evaluations"]["agent_alpha"]["summary"]
        assert s["correct_tasks"] == 7

    def test_total_tasks(self, report):
        s = report["agent_evaluations"]["agent_alpha"]["summary"]
        assert s["total_tasks"] == 8

    def test_correct_questions(self, report):
        s = report["agent_evaluations"]["agent_alpha"]["summary"]
        assert s["correct_questions"] == 26

    def test_total_questions(self, report):
        s = report["agent_evaluations"]["agent_alpha"]["summary"]
        assert s["total_questions"] == 27

    def test_correct_written_questions(self, report):
        s = report["agent_evaluations"]["agent_alpha"]["summary"]
        assert s["correct_written_questions"] == 22

    def test_correct_vision_questions(self, report):
        s = report["agent_evaluations"]["agent_alpha"]["summary"]
        assert s["correct_vision_questions"] == 4

    def test_correct_written_tasks(self, report):
        s = report["agent_evaluations"]["agent_alpha"]["summary"]
        assert s["correct_written_tasks"] == 6

    def test_correct_vision_tasks(self, report):
        s = report["agent_evaluations"]["agent_alpha"]["summary"]
        assert s["correct_vision_tasks"] == 3

    def test_feature_sel_list_mismatch(self, report):
        """Alpha reports 'bp' instead of 'blood_pressure' in list - should fail."""
        caps = report["agent_evaluations"]["agent_alpha"]["capsule_results"]
        fs = next(c for c in caps if c["capsule_id"] == "cap-feature-sel")
        assert fs["correct_written_answers"] == 2
        assert fs["total_written_questions"] == 3

    def test_mc_pi_all_correct(self, report):
        caps = report["agent_evaluations"]["agent_alpha"]["capsule_results"]
        mc = next(c for c in caps if c["capsule_id"] == "cap-mc-pi")
        assert mc["correct_written_answers"] == 2
        assert mc["total_written_questions"] == 2

    def test_meta_analysis_vision_only(self, report):
        caps = report["agent_evaluations"]["agent_alpha"]["capsule_results"]
        ma = next(c for c in caps if c["capsule_id"] == "cap-meta-analysis")
        assert ma["total_written_questions"] == 0
        assert ma["total_vision_questions"] == 2
        assert ma["correct_vision_answers"] == 2


class TestAgentBeta:
    def test_correct_tasks(self, report):
        s = report["agent_evaluations"]["agent_beta"]["summary"]
        assert s["correct_tasks"] == 4

    def test_correct_questions(self, report):
        s = report["agent_evaluations"]["agent_beta"]["summary"]
        assert s["correct_questions"] == 23

    def test_correct_written_questions(self, report):
        s = report["agent_evaluations"]["agent_beta"]["summary"]
        assert s["correct_written_questions"] == 20

    def test_correct_vision_questions(self, report):
        s = report["agent_evaluations"]["agent_beta"]["summary"]
        assert s["correct_vision_questions"] == 3

    def test_correct_written_tasks(self, report):
        s = report["agent_evaluations"]["agent_beta"]["summary"]
        assert s["correct_written_tasks"] == 4

    def test_correct_vision_tasks(self, report):
        s = report["agent_evaluations"]["agent_beta"]["summary"]
        assert s["correct_vision_tasks"] == 2

    def test_cls_eval_percentage_handling(self, report):
        """Beta submits accuracy as '94.5%' which should parse correctly,
        but precision=92.0 fails against zero-variance gt=92.3."""
        caps = report["agent_evaluations"]["agent_beta"]["capsule_results"]
        ce = next(c for c in caps if c["capsule_id"] == "cap-cls-eval")
        assert ce["correct_written_answers"] == 3

    def test_nn_train_boundary_case(self, report):
        """Beta's test_loss=0.40 is just barely outside the prediction interval."""
        caps = report["agent_evaluations"]["agent_beta"]["capsule_results"]
        nn = next(c for c in caps if c["capsule_id"] == "cap-nn-train")
        assert nn["correct_written_answers"] == 2

    def test_regress_zero_var_intercept(self, report):
        """Beta reports intercept=12.5, gt is zero-variance 12.456 -> wrong."""
        caps = report["agent_evaluations"]["agent_beta"]["capsule_results"]
        rg = next(c for c in caps if c["capsule_id"] == "cap-regress")
        assert rg["correct_written_answers"] == 4

    def test_meta_analysis_wrong_heterogeneity(self, report):
        """Beta reports 'high' but gt is 'moderate'."""
        caps = report["agent_evaluations"]["agent_beta"]["capsule_results"]
        ma = next(c for c in caps if c["capsule_id"] == "cap-meta-analysis")
        assert ma["correct_vision_answers"] == 1


class TestAgentGamma:
    def test_correct_tasks(self, report):
        s = report["agent_evaluations"]["agent_gamma"]["summary"]
        assert s["correct_tasks"] == 3

    def test_correct_questions(self, report):
        s = report["agent_evaluations"]["agent_gamma"]["summary"]
        assert s["correct_questions"] == 16

    def test_correct_written_questions(self, report):
        s = report["agent_evaluations"]["agent_gamma"]["summary"]
        assert s["correct_written_questions"] == 13

    def test_correct_vision_questions(self, report):
        s = report["agent_evaluations"]["agent_gamma"]["summary"]
        assert s["correct_vision_questions"] == 3

    def test_correct_written_tasks(self, report):
        s = report["agent_evaluations"]["agent_gamma"]["summary"]
        assert s["correct_written_tasks"] == 2

    def test_correct_vision_tasks(self, report):
        s = report["agent_evaluations"]["agent_gamma"]["summary"]
        assert s["correct_vision_tasks"] == 2

    def test_mc_pi_string_coercion(self, report):
        """Gamma submits values as strings '3.14' and '10000' - should parse OK."""
        caps = report["agent_evaluations"]["agent_gamma"]["capsule_results"]
        mc = next(c for c in caps if c["capsule_id"] == "cap-mc-pi")
        assert mc["correct_written_answers"] == 2

    def test_cls_eval_all_percentages(self, report):
        """Gamma submits all values as '94.5%', '92.3%', '96.7%' - should all parse."""
        caps = report["agent_evaluations"]["agent_gamma"]["capsule_results"]
        ce = next(c for c in caps if c["capsule_id"] == "cap-cls-eval")
        assert ce["correct_written_answers"] == 4

    def test_nn_train_boundary_accuracy(self, report):
        """Gamma's test_accuracy=85.0 is just barely inside the prediction interval."""
        caps = report["agent_evaluations"]["agent_gamma"]["capsule_results"]
        nn = next(c for c in caps if c["capsule_id"] == "cap-nn-train")
        # test_accuracy correct, test_loss correct, epochs_run wrong (45 vs 50 zero-var)
        assert nn["correct_written_answers"] == 2

    def test_bootstrap_all_outside(self, report):
        """Gamma's bootstrap values 60, 55, 65 are all outside prediction intervals."""
        caps = report["agent_evaluations"]["agent_gamma"]["capsule_results"]
        bs = next(c for c in caps if c["capsule_id"] == "cap-bootstrap")
        assert bs["correct_written_answers"] == 0

    def test_feature_sel_wrong_order(self, report):
        """Gamma reorders list elements - list comparison is order-sensitive."""
        caps = report["agent_evaluations"]["agent_gamma"]["capsule_results"]
        fs = next(c for c in caps if c["capsule_id"] == "cap-feature-sel")
        assert fs["correct_written_answers"] == 1  # only explained_var correct


class TestRankings:
    def test_by_correct_tasks(self, report):
        rankings = report["rankings"]["by_correct_tasks"]
        assert rankings == ["agent_alpha", "agent_beta", "agent_gamma"]

    def test_by_correct_questions(self, report):
        rankings = report["rankings"]["by_correct_questions"]
        assert rankings == ["agent_alpha", "agent_beta", "agent_gamma"]


class TestQuestionCategorization:
    """These totals are properties of the ground truth and should be identical across agents."""

    def test_total_written_and_vision_counts(self, report):
        for agent_name, agent_data in report["agent_evaluations"].items():
            s = agent_data["summary"]
            assert s["total_written_questions"] == 23, f"{agent_name} total_written wrong"
            assert s["total_vision_questions"] == 4, f"{agent_name} total_vision wrong"
            assert s["total_questions"] == 27, f"{agent_name} total_questions wrong"

    def test_total_written_tasks(self, report):
        for agent_data in report["agent_evaluations"].values():
            assert agent_data["summary"]["total_written_tasks"] == 7

    def test_total_vision_tasks(self, report):
        for agent_data in report["agent_evaluations"].values():
            assert agent_data["summary"]["total_vision_tasks"] == 3


class TestPredictionIntervalAccuracy:
    """Independently verify prediction interval computations against known cases."""

    def test_independent_pi_mc_pi(self, ground_truth):
        """Compute prediction interval for cap-mc-pi estimated_pi and verify
        that agent values 3.14 and 3.2 fall within it."""
        mc_pi = next(c for c in ground_truth if c["capsule_id"] == "cap-mc-pi")
        values = [r["estimated_pi"] for r in mc_pi["results"]]

        n = len(values)
        mean = np.mean(values)
        std = np.std(values, ddof=1)
        t_val = t_dist.ppf(0.975, n - 1)
        lower = mean - t_val * std * math.sqrt(1 + 1 / n)
        upper = mean + t_val * std * math.sqrt(1 + 1 / n)

        # Alpha reports 3.14
        assert lower <= 3.14 <= upper
        # Beta reports 3.2
        assert lower <= 3.2 <= upper
        # Gamma reports "3.14" -> parsed to 3.14
        assert lower <= 3.14 <= upper

    def test_independent_pi_nn_test_loss(self, ground_truth):
        """Verify that 0.40 is outside the prediction interval for test_loss."""
        nn = next(c for c in ground_truth if c["capsule_id"] == "cap-nn-train")
        values = [r["test_loss"] for r in nn["results"]]

        n = len(values)
        mean = np.mean(values)
        std = np.std(values, ddof=1)
        t_val = t_dist.ppf(0.975, n - 1)
        upper = mean + t_val * std * math.sqrt(1 + 1 / n)

        # Beta reports 0.40 - should be outside
        assert 0.40 > upper

    def test_independent_pi_nn_test_accuracy(self, ground_truth):
        """Verify that 85.0 is inside the prediction interval for test_accuracy."""
        nn = next(c for c in ground_truth if c["capsule_id"] == "cap-nn-train")
        values = [r["test_accuracy"] for r in nn["results"]]

        n = len(values)
        mean = np.mean(values)
        std = np.std(values, ddof=1)
        t_val = t_dist.ppf(0.975, n - 1)
        lower = mean - t_val * std * math.sqrt(1 + 1 / n)

        # Gamma reports 85.0 - should be (barely) inside
        assert 85.0 >= lower

    def test_zero_variance_requires_exact(self, ground_truth):
        """Zero-variance capsules should have collapsed prediction intervals."""
        cls = next(c for c in ground_truth if c["capsule_id"] == "cap-cls-eval")
        values = [r["precision"] for r in cls["results"]]

        std = np.std(values, ddof=1)
        assert std == 0.0

        # Beta reports 92.0 for precision (gt is 92.3) - must fail
        assert 92.0 != 92.3

    def test_vision_only_capsule_structure(self, report):
        """cap-meta-analysis has only vision questions - verify counts."""
        for agent_name in ["agent_alpha", "agent_beta", "agent_gamma"]:
            caps = report["agent_evaluations"][agent_name]["capsule_results"]
            ma = next(c for c in caps if c["capsule_id"] == "cap-meta-analysis")
            assert ma["total_written_questions"] == 0
            assert ma["total_vision_questions"] == 2


class TestMethodology:
    """Verify the methodology specification reflects correct statistical choices."""

    @pytest.fixture
    def methodology(self):
        with open(METHODOLOGY_PATH) as f:
            return json.load(f)

    def test_has_all_required_fields(self, methodology):
        required = {
            "distribution", "degrees_of_freedom", "variance_estimator",
            "interval_type", "interval_half_width_formula", "string_comparison",
            "vision_classification_rule", "submission_preprocessing"
        }
        assert set(methodology.keys()) >= required, (
            f"Missing fields: {required - set(methodology.keys())}"
        )

    def test_distribution_is_t(self, methodology):
        """t-distribution is required for n=3 (normal requires large samples)."""
        assert methodology["distribution"] == "t"

    def test_degrees_of_freedom(self, methodology):
        assert methodology["degrees_of_freedom"] == "n-1"

    def test_variance_estimator_is_bessel(self, methodology):
        """Bessel's correction (ddof=1) is required for sample variance."""
        assert methodology["variance_estimator"] == "bessel"

    def test_interval_type_is_prediction(self, methodology):
        """Prediction intervals predict new observations; confidence intervals
        estimate population parameters. For reproducibility assessment we need
        to predict where a new run's result would fall."""
        assert methodology["interval_type"] == "prediction"

    def test_interval_formula_is_prediction_not_confidence(self, methodology):
        """The prediction interval half-width is t*s*sqrt(1+1/n), not t*s/sqrt(n).
        The sqrt(1+1/n) factor accounts for both sampling uncertainty and
        prediction uncertainty for a new observation."""
        formula = methodology["interval_half_width_formula"].replace(" ", "").lower()
        assert "1+1/n" in formula, (
            "Formula must contain sqrt(1+1/n) for prediction interval, "
            "not 1/sqrt(n) for confidence interval"
        )

    def test_string_comparison_case_insensitive(self, methodology):
        assert methodology["string_comparison"] == "case_insensitive"

    def test_vision_rule_is_substring(self, methodology):
        """Vision keys contain 'fig' as substring (e.g. 'fig pooled_effect'),
        not necessarily as a prefix."""
        assert methodology["vision_classification_rule"] == "fig_substring"

    def test_preprocessing_includes_percent_strip(self, methodology):
        pp = methodology["submission_preprocessing"]
        assert "percent_strip" in pp, "Must handle percentage signs in submissions"

    def test_preprocessing_includes_string_to_number(self, methodology):
        pp = methodology["submission_preprocessing"]
        assert "string_to_number" in pp, "Must coerce string-encoded numbers"
