
"""Tests for the benchmark evaluation pipeline.

Verifies correct metric computation, hack detection, OPT@K values,
leaderboard ranking, and bootstrap confidence intervals.
"""

import pytest
import json
import subprocess
import sys
import os


# ===========================================================================
# Fixture: run pipeline once, load output
# ===========================================================================


@pytest.fixture(scope="session")
def pipeline_output():
    """Run the full pipeline (extraction + evaluation) and return parsed output."""
    result = subprocess.run(
        ["bash", "/app/run.sh"],
        capture_output=True,
        text=True,
        cwd="/app",
    )
    if result.returncode != 0:
        pytest.fail(
            f"Pipeline failed with exit code {result.returncode}:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    output_path = "/app/output/leaderboard.json"
    assert os.path.exists(output_path), "Pipeline did not produce output file"

    with open(output_path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def leaderboard(pipeline_output):
    return pipeline_output["leaderboard"]


@pytest.fixture(scope="session")
def details(pipeline_output):
    return pipeline_output["details"]


@pytest.fixture(scope="session")
def lb_by_model(leaderboard):
    return {e["model"]: e for e in leaderboard}


# ===========================================================================
# Test 1: Leaderboard ranking order
# ===========================================================================


class TestLeaderboardRanking:
    def test_ranking_order(self, leaderboard):
        """Leaderboard must be sorted by hack-adjusted OPT@2 descending."""
        assert len(leaderboard) == 4
        assert leaderboard[0]["model"] == "Gamma"
        assert leaderboard[1]["model"] == "Alpha"
        assert leaderboard[2]["model"] == "Delta"
        assert leaderboard[3]["model"] == "Beta"

    def test_ranks_assigned(self, leaderboard):
        """Each entry should have correct rank."""
        for i, entry in enumerate(leaderboard):
            assert entry["rank"] == i + 1


# ===========================================================================
# Test 2: Hack-adjusted OPT@2 values
# ===========================================================================


class TestHackAdjustedOpt:
    def test_gamma_hack_adj_opt2(self, lb_by_model):
        """Gamma: all 5 tasks pass after hack adjustment -> 1.0."""
        assert abs(lb_by_model["Gamma"]["hack_adjusted_opt_at_2"] - 1.0) < 0.01

    def test_alpha_hack_adj_opt2(self, lb_by_model):
        """Alpha: 4/5 tasks pass -> 0.8."""
        assert abs(lb_by_model["Alpha"]["hack_adjusted_opt_at_2"] - 0.8) < 0.01

    def test_delta_hack_adj_opt2(self, lb_by_model):
        """Delta: 3/5 tasks pass -> 0.6."""
        assert abs(lb_by_model["Delta"]["hack_adjusted_opt_at_2"] - 0.6) < 0.01

    def test_beta_hack_adj_opt2(self, lb_by_model):
        """Beta: 1/5 tasks pass after hack removal -> 0.2."""
        assert abs(lb_by_model["Beta"]["hack_adjusted_opt_at_2"] - 0.2) < 0.01


# ===========================================================================
# Test 3: Regular OPT@1 values
# ===========================================================================


class TestRegularOpt1:
    def test_alpha_opt1(self, lb_by_model):
        """Alpha OPT@1: T1,T2,T4 pass -> 3/5 = 0.6."""
        assert abs(lb_by_model["Alpha"]["opt_at_1"] - 0.6) < 0.01

    def test_beta_opt1(self, lb_by_model):
        """Beta OPT@1: no first attempts pass -> 0/5 = 0.0."""
        assert abs(lb_by_model["Beta"]["opt_at_1"] - 0.0) < 0.01

    def test_gamma_opt1(self, lb_by_model):
        """Gamma OPT@1: T2,T3,T4,T5 pass (T1 incorrect) -> 4/5 = 0.8."""
        assert abs(lb_by_model["Gamma"]["opt_at_1"] - 0.8) < 0.01

    def test_delta_opt1(self, lb_by_model):
        """Delta OPT@1: T1,T2 pass -> 2/5 = 0.4."""
        assert abs(lb_by_model["Delta"]["opt_at_1"] - 0.4) < 0.01


# ===========================================================================
# Test 4: Regular OPT@2 values
# ===========================================================================


class TestRegularOpt2:
    def test_alpha_opt2(self, lb_by_model):
        """Alpha OPT@2: T3 passes at a1 -> 4/5 = 0.8."""
        assert abs(lb_by_model["Alpha"]["opt_at_2"] - 0.8) < 0.01

    def test_beta_opt2(self, lb_by_model):
        """Beta OPT@2: T1,T2,T4,T5 pass at a1 -> 4/5 = 0.8."""
        assert abs(lb_by_model["Beta"]["opt_at_2"] - 0.8) < 0.01

    def test_gamma_opt2(self, lb_by_model):
        """Gamma OPT@2: T1 passes at a1 -> 5/5 = 1.0."""
        assert abs(lb_by_model["Gamma"]["opt_at_2"] - 1.0) < 0.01

    def test_delta_opt2(self, lb_by_model):
        """Delta OPT@2: T4 passes at a1 -> 3/5 = 0.6."""
        assert abs(lb_by_model["Delta"]["opt_at_2"] - 0.6) < 0.01


# ===========================================================================
# Test 5: Hack detection counts
# ===========================================================================


class TestHackCounts:
    def test_alpha_no_hacks(self, lb_by_model):
        assert lb_by_model["Alpha"]["num_hacks"] == 0

    def test_beta_four_hacks(self, lb_by_model):
        """Beta has 4 hacks: T1a0, T2a1, T4a1, T5a1."""
        assert lb_by_model["Beta"]["num_hacks"] == 4

    def test_gamma_one_hack(self, lb_by_model):
        """Gamma has 1 hack: T2a0 (feature deletion)."""
        assert lb_by_model["Gamma"]["num_hacks"] == 1

    def test_delta_no_hacks(self, lb_by_model):
        assert lb_by_model["Delta"]["num_hacks"] == 0


# ===========================================================================
# Test 6: Specific hack detection in details
# ===========================================================================


class TestHackDetectionDetails:
    def test_beta_t1_a0_is_hack(self, details):
        """Beta T1 a0 has test-specific shape check."""
        assert details["T1"]["Beta"][0]["is_hack"] is True

    def test_beta_t2_a1_is_hack(self, details):
        """Beta T2 a1 has memoization injection."""
        assert details["T2"]["Beta"][1]["is_hack"] is True

    def test_beta_t4_a1_is_hack(self, details):
        """Beta T4 a1 has compiler flag manipulation."""
        assert details["T4"]["Beta"][1]["is_hack"] is True

    def test_beta_t5_a1_is_hack(self, details):
        """Beta T5 a1 has environment manipulation."""
        assert details["T5"]["Beta"][1]["is_hack"] is True

    def test_gamma_t2_a0_is_hack(self, details):
        """Gamma T2 a0 has feature deletion."""
        assert details["T2"]["Gamma"][0]["is_hack"] is True

    def test_no_false_positives(self, details):
        """All non-hack attempts must NOT be flagged."""
        expected_hacks = {
            ("T1", "Beta", 0),
            ("T2", "Beta", 1),
            ("T4", "Beta", 1),
            ("T5", "Beta", 1),
            ("T2", "Gamma", 0),
        }
        for task_id in details:
            for model_id in details[task_id]:
                for attempt in details[task_id][model_id]:
                    key = (task_id, model_id, attempt["attempt"])
                    if key in expected_hacks:
                        continue
                    assert attempt["is_hack"] is False, (
                        f"{task_id}/{model_id}/a{attempt['attempt']} "
                        f"falsely flagged as hack"
                    )


# ===========================================================================
# Test 7: Specific speedup values (harmonic mean, correct direction)
# ===========================================================================


class TestSpeedupValues:
    def test_alpha_t1_a0_speedup(self, details):
        """Alpha T1 a0: h/m = [5/4, 10/8] = [1.25, 1.25], harmonic = 1.25."""
        assert abs(details["T1"]["Alpha"][0]["speedup"] - 1.25) < 0.01

    def test_beta_t1_a0_speedup(self, details):
        """Beta T1 a0: h/m = [5/1, 10/100] = [5.0, 0.1], harmonic = 0.1961.
        This demonstrates gaming resistance --- geometric mean would give ~0.707."""
        assert abs(details["T1"]["Beta"][0]["speedup"] - 0.1961) < 0.01

    def test_gamma_t1_a1_speedup(self, details):
        """Gamma T1 a1: h/m = [5/4, 10/7.5] = [1.25, 1.333],
        harmonic = 2/(0.8+0.75) = 1.2903."""
        assert abs(details["T1"]["Gamma"][1]["speedup"] - 1.2903) < 0.01

    def test_gamma_t2_a1_speedup(self, details):
        """Gamma T2 a1: h/m = [4/3.5, 8/7.2, 12/10.8],
        harmonic = 3/(0.875+0.9+0.9) = 1.1215."""
        assert abs(details["T2"]["Gamma"][1]["speedup"] - 1.1215) < 0.01

    def test_alpha_t2_a0_speedup(self, details):
        """Alpha T2 a0: h/m = [4/3.8, 8/7.5, 12/11],
        harmonic = 3/(0.95+0.9375+0.9167) = 1.0698."""
        assert abs(details["T2"]["Alpha"][0]["speedup"] - 1.0698) < 0.01

    def test_delta_t5_a0_speedup(self, details):
        """Delta T5 a0: h/m = [3/3.2, 6/6.5, 9/9.8],
        harmonic = 3/(1.0667+1.0833+1.0889) = 0.9262."""
        assert abs(details["T5"]["Delta"][0]["speedup"] - 0.9262) < 0.01

    def test_gamma_t3_a0_speedup(self, details):
        """Gamma T3 a0: h/m = [2/1.8, 4/3.5],
        harmonic = 2/(0.9+0.875) = 1.1268."""
        assert abs(details["T3"]["Gamma"][0]["speedup"] - 1.1268) < 0.01

    def test_beta_t2_a0_speedup(self, details):
        """Beta T2 a0: h/m = [4/4.2, 8/8.5, 12/12.8],
        harmonic = 3/(1.05+1.0625+1.0667) = 0.9436."""
        assert abs(details["T2"]["Beta"][0]["speedup"] - 0.9436) < 0.01


# ===========================================================================
# Test 8: OPT field in details (raw, without hack adjustment)
# ===========================================================================


class TestOptField:
    def test_alpha_t1_a0_opt(self, details):
        """Alpha T1 a0: speedup 1.25 >= 0.95, correct -> opt = True."""
        assert details["T1"]["Alpha"][0]["opt"] is True

    def test_alpha_t5_a0_opt(self, details):
        """Alpha T5 a0: speedup 0.857 < 0.95 -> opt = False."""
        assert details["T5"]["Alpha"][0]["opt"] is False

    def test_gamma_t1_a0_opt(self, details):
        """Gamma T1 a0: incorrect -> opt = False regardless of speedup."""
        assert details["T1"]["Gamma"][0]["opt"] is False

    def test_beta_t3_a1_opt(self, details):
        """Beta T3 a1: speedup 1.0 >= 0.95 but incorrect -> opt = False."""
        assert details["T3"]["Beta"][1]["opt"] is False


# ===========================================================================
# Test 9: Bootstrap confidence intervals
# ===========================================================================


class TestBootstrapCI:
    def test_ci_fields_present(self, leaderboard):
        """Each leaderboard entry must have ci_lower and ci_upper."""
        for entry in leaderboard:
            assert "ci_lower" in entry, f"{entry['model']} missing ci_lower"
            assert "ci_upper" in entry, f"{entry['model']} missing ci_upper"

    def test_ci_contains_point_estimate(self, leaderboard):
        """CI must contain the hack-adjusted OPT@2 point estimate."""
        for entry in leaderboard:
            point = entry["hack_adjusted_opt_at_2"]
            assert entry["ci_lower"] <= point + 0.001, (
                f"{entry['model']}: ci_lower {entry['ci_lower']} > "
                f"point estimate {point}"
            )
            assert entry["ci_upper"] >= point - 0.001, (
                f"{entry['model']}: ci_upper {entry['ci_upper']} < "
                f"point estimate {point}"
            )

    def test_ci_in_valid_range(self, leaderboard):
        """CIs must be in [0, 1]."""
        for entry in leaderboard:
            assert 0.0 <= entry["ci_lower"] <= 1.0, (
                f"{entry['model']}: ci_lower {entry['ci_lower']} out of range"
            )
            assert 0.0 <= entry["ci_upper"] <= 1.0, (
                f"{entry['model']}: ci_upper {entry['ci_upper']} out of range"
            )

    def test_ci_ordering(self, leaderboard):
        """ci_lower must be <= ci_upper."""
        for entry in leaderboard:
            assert entry["ci_lower"] <= entry["ci_upper"], (
                f"{entry['model']}: ci_lower {entry['ci_lower']} > "
                f"ci_upper {entry['ci_upper']}"
            )

    def test_top_bottom_separation(self, leaderboard):
        """Gamma (1.0) and Beta (0.2) CIs should not overlap."""
        gamma = next(e for e in leaderboard if e["model"] == "Gamma")
        beta = next(e for e in leaderboard if e["model"] == "Beta")
        assert gamma["ci_lower"] > beta["ci_upper"], (
            f"Gamma ci_lower {gamma['ci_lower']} should be > "
            f"Beta ci_upper {beta['ci_upper']}"
        )


# ===========================================================================
# Test 10: Hack-adjusted OPT@1 values
# ===========================================================================


class TestHackAdjustedOpt1:
    def test_alpha_hack_adj_opt1(self, lb_by_model):
        """Alpha (no hacks): hack-adj OPT@1 = regular OPT@1 = 0.6."""
        assert abs(lb_by_model["Alpha"]["hack_adjusted_opt_at_1"] - 0.6) < 0.01

    def test_beta_hack_adj_opt1(self, lb_by_model):
        """Beta: after removing T1a0 hack, first non-hack=a1 passes.
        Others fail. -> 1/5 = 0.2."""
        assert abs(lb_by_model["Beta"]["hack_adjusted_opt_at_1"] - 0.2) < 0.01

    def test_gamma_hack_adj_opt1(self, lb_by_model):
        """Gamma: after removing T2a0 hack, first non-hack=a1 passes.
        Same as regular -> 0.8."""
        assert abs(lb_by_model["Gamma"]["hack_adjusted_opt_at_1"] - 0.8) < 0.01

    def test_delta_hack_adj_opt1(self, lb_by_model):
        """Delta (no hacks): hack-adj OPT@1 = regular OPT@1 = 0.4."""
        assert abs(lb_by_model["Delta"]["hack_adjusted_opt_at_1"] - 0.4) < 0.01


# ===========================================================================
# Test 11: Correct field is proper boolean (not SQLite integer)
# ===========================================================================


class TestCorrectFieldType:
    def test_correct_true_is_bool(self, details):
        """Alpha T1 a0 correct field must be boolean True, not integer 1."""
        assert details["T1"]["Alpha"][0]["correct"] is True

    def test_correct_false_is_bool(self, details):
        """Gamma T1 a0 correct field must be boolean False, not integer 0."""
        assert details["T1"]["Gamma"][0]["correct"] is False

    def test_correct_type_consistency(self, details):
        """All correct fields must be proper booleans."""
        for task_id in details:
            for model_id in details[task_id]:
                for attempt in details[task_id][model_id]:
                    assert isinstance(attempt["correct"], bool), (
                        f"{task_id}/{model_id}/a{attempt['attempt']}: "
                        f"correct is {type(attempt['correct']).__name__}, expected bool"
                    )
