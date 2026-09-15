
"""Tests for the multi-task clinical challenge evaluation system."""

import json
import math
import os
import pytest

RESULTS_PATH = "/app/results.json"
STABILITY_PATH = "/app/stability.json"

ATOL = 1e-4
ATOL_CI = 0.02
ATOL_STAB = 0.025  # tolerance for rank-stability probabilities

TEAMS = ["alpha", "beta", "gamma", "delta"]


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}."
    )
    with open(RESULTS_PATH, "r") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def stability():
    assert os.path.exists(STABILITY_PATH), (
        f"Stability file not found at {STABILITY_PATH}."
    )
    with open(STABILITY_PATH, "r") as f:
        return json.load(f)


# ============================================================
# Results structure tests
# ============================================================

class TestResultsStructure:
    """Verify the output JSON has the required schema."""

    def test_has_teams_key(self, results):
        assert "teams" in results

    def test_has_rankings_key(self, results):
        assert "rankings" in results

    def test_all_teams_present(self, results):
        expected_teams = set(TEAMS)
        assert set(results["teams"].keys()) == expected_teams
        assert set(results["rankings"].keys()) == expected_teams

    def test_team_schema(self, results):
        for team_name, team_data in results["teams"].items():
            assert "segmentation" in team_data, f"{team_name}: missing segmentation"
            assert "staging" in team_data, f"{team_name}: missing staging"
            assert "prognosis" in team_data, f"{team_name}: missing prognosis"
            assert "overall" in team_data, f"{team_name}: missing overall"
            assert "bootstrap_ci" in team_data, f"{team_name}: missing bootstrap_ci"

            seg = team_data["segmentation"]
            assert "class_1_agg_dsc" in seg
            assert "class_2_agg_dsc" in seg
            assert "mean_agg_dsc" in seg

            stg = team_data["staging"]
            assert "balanced_accuracy_T" in stg
            assert "balanced_accuracy_N" in stg
            assert "mean_balanced_accuracy" in stg

            prog = team_data["prognosis"]
            assert "c_index" in prog

            ovr = team_data["overall"]
            for key in ["segmentation_score", "staging_score", "prognosis_score",
                        "weighted_score", "unweighted_score", "consistency", "rank"]:
                assert key in ovr, f"{team_name}: missing overall.{key}"

            ci = team_data["bootstrap_ci"]
            for metric in ["seg", "staging", "prognosis", "weighted"]:
                assert metric in ci, f"{team_name}: missing bootstrap_ci.{metric}"
                assert "lower" in ci[metric]
                assert "upper" in ci[metric]


# ============================================================
# Segmentation metric tests
# ============================================================

class TestSegmentationMetrics:
    """Verify aggregated DSC computation."""

    EXPECTED = {
        "alpha": {"c1": 0.6905853348, "c2": 0.6683063750, "mean": 0.6794458549},
        "beta":  {"c1": 0.5295397980, "c2": 0.4876321502, "mean": 0.5085859741},
        "gamma": {"c1": 0.7331556831, "c2": 0.7592465654, "mean": 0.7462011243},
        "delta": {"c1": 0.6226113782, "c2": 0.5936631462, "mean": 0.6081372622},
    }

    @pytest.mark.parametrize("team", TEAMS)
    def test_class_1_agg_dsc(self, results, team):
        actual = results["teams"][team]["segmentation"]["class_1_agg_dsc"]
        expected = self.EXPECTED[team]["c1"]
        assert abs(actual - expected) < ATOL, (
            f"{team} class_1_agg_dsc: expected {expected:.6f}, got {actual:.6f}"
        )

    @pytest.mark.parametrize("team", TEAMS)
    def test_class_2_agg_dsc(self, results, team):
        actual = results["teams"][team]["segmentation"]["class_2_agg_dsc"]
        expected = self.EXPECTED[team]["c2"]
        assert abs(actual - expected) < ATOL, (
            f"{team} class_2_agg_dsc: expected {expected:.6f}, got {actual:.6f}"
        )

    @pytest.mark.parametrize("team", TEAMS)
    def test_mean_agg_dsc(self, results, team):
        actual = results["teams"][team]["segmentation"]["mean_agg_dsc"]
        expected = self.EXPECTED[team]["mean"]
        assert abs(actual - expected) < ATOL, (
            f"{team} mean_agg_dsc: expected {expected:.6f}, got {actual:.6f}"
        )

    def test_aggregated_not_averaged(self, results):
        """Micro-averaged DSC must differ from naive per-patient averaging."""
        actual = results["teams"]["gamma"]["segmentation"]["class_1_agg_dsc"]
        assert 0.70 < actual < 0.77, (
            f"gamma class_1 DSC {actual} outside expected range"
        )


# ============================================================
# Staging metric tests
# ============================================================

class TestStagingMetrics:
    """Verify balanced accuracy computation."""

    EXPECTED = {
        "alpha": {"T": 0.9166666667, "N": 0.6708333333, "mean": 0.7937500000},
        "beta":  {"T": 0.7041666667, "N": 0.6208333333, "mean": 0.6625000000},
        "gamma": {"T": 0.8666666667, "N": 0.9500000000, "mean": 0.9083333333},
        "delta": {"T": 0.7541666667, "N": 0.8041666667, "mean": 0.7791666667},
    }

    @pytest.mark.parametrize("team", TEAMS)
    def test_balanced_accuracy_T(self, results, team):
        actual = results["teams"][team]["staging"]["balanced_accuracy_T"]
        expected = self.EXPECTED[team]["T"]
        assert abs(actual - expected) < ATOL, (
            f"{team} BA_T: expected {expected:.6f}, got {actual:.6f}"
        )

    @pytest.mark.parametrize("team", TEAMS)
    def test_balanced_accuracy_N(self, results, team):
        actual = results["teams"][team]["staging"]["balanced_accuracy_N"]
        expected = self.EXPECTED[team]["N"]
        assert abs(actual - expected) < ATOL, (
            f"{team} BA_N: expected {expected:.6f}, got {actual:.6f}"
        )

    @pytest.mark.parametrize("team", TEAMS)
    def test_mean_balanced_accuracy(self, results, team):
        actual = results["teams"][team]["staging"]["mean_balanced_accuracy"]
        expected = self.EXPECTED[team]["mean"]
        assert abs(actual - expected) < ATOL, (
            f"{team} mean_BA: expected {expected:.6f}, got {actual:.6f}"
        )


# ============================================================
# Prognosis metric tests
# ============================================================

class TestPrognosisMetrics:
    """Verify concordance index with correct NaN handling."""

    EXPECTED = {
        "alpha": 0.9518072289,
        "beta":  0.7771084337,
        "gamma": 0.9759036145,
        "delta": 0.8313253012,
    }

    # Exclusion approach yields different values for teams with NaN:
    EXCLUSION_BETA = 0.9107142857
    EXCLUSION_DELTA = 0.8873239437

    @pytest.mark.parametrize("team", TEAMS)
    def test_c_index(self, results, team):
        actual = results["teams"][team]["prognosis"]["c_index"]
        expected = self.EXPECTED[team]
        assert abs(actual - expected) < ATOL, (
            f"{team} c_index: expected {expected:.6f}, got {actual:.6f}"
        )

    def test_nan_penalty_not_exclusion(self, results):
        """Verify NaN policy is tie-penalty (Approach B), not exclusion (A).

        Under exclusion, beta C-index would be ~0.9107. Under tie-penalty
        it should be ~0.7771. The correct approach (per audit) is B.
        """
        beta_ci = results["teams"]["beta"]["prognosis"]["c_index"]
        assert beta_ci < 0.85, (
            f"Beta C-index {beta_ci:.4f} too high — likely using exclusion "
            f"approach instead of tie-penalty"
        )

    def test_nan_handling_penalizes(self, results):
        """Teams with NaN predictions should have lower C-index than without."""
        beta_ci = results["teams"]["beta"]["prognosis"]["c_index"]
        alpha_ci = results["teams"]["alpha"]["prognosis"]["c_index"]
        assert beta_ci < alpha_ci


# ============================================================
# Overall ranking tests
# ============================================================

class TestOverallRanking:
    """Verify weighted ranking and tie-breaking."""

    EXPECTED_WEIGHTED = {
        "alpha": 0.8283968553,
        "beta":  0.6698648670,
        "gamma": 0.8948283935,
        "delta": 0.7572727694,
    }

    EXPECTED_RANKINGS = {
        "gamma": 1,
        "alpha": 2,
        "delta": 3,
        "beta":  4,
    }

    @pytest.mark.parametrize("team", TEAMS)
    def test_weighted_score(self, results, team):
        actual = results["teams"][team]["overall"]["weighted_score"]
        expected = self.EXPECTED_WEIGHTED[team]
        assert abs(actual - expected) < ATOL, (
            f"{team} weighted: expected {expected:.6f}, got {actual:.6f}"
        )

    @pytest.mark.parametrize("team", TEAMS)
    def test_ranking(self, results, team):
        actual = results["teams"][team]["overall"]["rank"]
        expected = self.EXPECTED_RANKINGS[team]
        assert actual == expected, (
            f"{team} rank: expected {expected}, got {actual}"
        )

    def test_rankings_dict(self, results):
        for team, expected_rank in self.EXPECTED_RANKINGS.items():
            actual = results["rankings"][team]
            assert actual == expected_rank

    @pytest.mark.parametrize("team", TEAMS)
    def test_weight_formula(self, results, team):
        """Verify weighted score = 0.25*seg + 0.35*staging + 0.40*prognosis."""
        ovr = results["teams"][team]["overall"]
        expected = (0.25 * ovr["segmentation_score"] +
                    0.35 * ovr["staging_score"] +
                    0.40 * ovr["prognosis_score"])
        assert abs(ovr["weighted_score"] - expected) < 1e-8

    @pytest.mark.parametrize("team", TEAMS)
    def test_consistency_formula(self, results, team):
        """Verify consistency = |weighted - unweighted|."""
        ovr = results["teams"][team]["overall"]
        unweighted = (ovr["segmentation_score"] + ovr["staging_score"] +
                      ovr["prognosis_score"]) / 3.0
        assert abs(ovr["unweighted_score"] - unweighted) < 1e-8
        expected_cons = abs(ovr["weighted_score"] - unweighted)
        assert abs(ovr["consistency"] - expected_cons) < 1e-8


# ============================================================
# Bootstrap CI tests
# ============================================================

class TestBootstrapCI:
    """Verify bootstrap confidence intervals."""

    EXPECTED_WEIGHTED_CI = {
        "alpha": {"lower": 0.7696524770, "upper": 0.8860565175},
        "beta":  {"lower": 0.5800950236, "upper": 0.7443599469},
        "gamma": {"lower": 0.8415152358, "upper": 0.9384945546},
        "delta": {"lower": 0.6874946539, "upper": 0.8248907351},
    }

    @pytest.mark.parametrize("team", TEAMS)
    def test_weighted_ci_lower(self, results, team):
        actual = results["teams"][team]["bootstrap_ci"]["weighted"]["lower"]
        expected = self.EXPECTED_WEIGHTED_CI[team]["lower"]
        assert abs(actual - expected) < ATOL_CI, (
            f"{team} weighted CI lower: expected {expected:.6f}, got {actual:.6f}"
        )

    @pytest.mark.parametrize("team", TEAMS)
    def test_weighted_ci_upper(self, results, team):
        actual = results["teams"][team]["bootstrap_ci"]["weighted"]["upper"]
        expected = self.EXPECTED_WEIGHTED_CI[team]["upper"]
        assert abs(actual - expected) < ATOL_CI, (
            f"{team} weighted CI upper: expected {expected:.6f}, got {actual:.6f}"
        )

    @pytest.mark.parametrize("team", TEAMS)
    def test_ci_bounds_ordering(self, results, team):
        ci = results["teams"][team]["bootstrap_ci"]
        for metric in ["seg", "staging", "prognosis", "weighted"]:
            lower = ci[metric]["lower"]
            upper = ci[metric]["upper"]
            assert lower <= upper, (
                f"{team} {metric}: lower ({lower}) > upper ({upper})"
            )

    @pytest.mark.parametrize("team", TEAMS)
    def test_point_estimate_within_ci(self, results, team):
        ovr = results["teams"][team]["overall"]
        ci = results["teams"][team]["bootstrap_ci"]["weighted"]
        margin = 0.05
        assert ci["lower"] - margin <= ovr["weighted_score"] <= ci["upper"] + margin


# ============================================================
# Cross-consistency tests
# ============================================================

class TestCrossConsistency:
    """Cross-check that individual metrics feed correctly into overall scores."""

    @pytest.mark.parametrize("team", TEAMS)
    def test_seg_score_matches_mean_dsc(self, results, team):
        seg = results["teams"][team]["segmentation"]["mean_agg_dsc"]
        ovr = results["teams"][team]["overall"]["segmentation_score"]
        assert abs(seg - ovr) < 1e-10

    @pytest.mark.parametrize("team", TEAMS)
    def test_staging_score_matches_mean_ba(self, results, team):
        stg = results["teams"][team]["staging"]["mean_balanced_accuracy"]
        ovr = results["teams"][team]["overall"]["staging_score"]
        assert abs(stg - ovr) < 1e-10

    @pytest.mark.parametrize("team", TEAMS)
    def test_prognosis_score_matches_cindex(self, results, team):
        ci = results["teams"][team]["prognosis"]["c_index"]
        ovr = results["teams"][team]["overall"]["prognosis_score"]
        assert abs(ci - ovr) < 1e-10

    def test_ranking_order_matches_scores(self, results):
        teams_by_score = sorted(
            results["teams"].items(),
            key=lambda x: -x[1]["overall"]["weighted_score"]
        )
        for expected_rank, (team, data) in enumerate(teams_by_score, 1):
            actual_rank = data["overall"]["rank"]
            assert actual_rank == expected_rank


# ============================================================
# Rank stability tests
# ============================================================

class TestStabilityStructure:
    """Verify stability.json structure."""

    def test_has_rank_probability_matrix(self, stability):
        assert "rank_probability_matrix" in stability

    def test_has_dominant_rank(self, stability):
        assert "dominant_rank" in stability

    def test_has_rank_certainty(self, stability):
        assert "rank_certainty" in stability

    def test_has_pairwise_dominance(self, stability):
        assert "pairwise_dominance" in stability

    def test_all_teams_in_stability(self, stability):
        for key in ["rank_probability_matrix", "dominant_rank",
                     "rank_certainty", "pairwise_dominance"]:
            assert set(stability[key].keys()) == set(TEAMS), (
                f"Missing teams in stability.{key}"
            )


class TestRankProbabilityMatrix:
    """Verify rank probability distributions."""

    EXPECTED_DOMINANT = {
        "gamma": 1,
        "alpha": 2,
        "delta": 3,
        "beta": 4,
    }

    EXPECTED_CERTAINTY = {
        "gamma": 0.9865,
        "alpha": 0.9465,
        "delta": 0.887,
        "beta": 0.927,
    }

    EXPECTED_RANK_PROBS = {
        "gamma": {"1": 0.9865, "2": 0.0135, "3": 0.0, "4": 0.0},
        "alpha": {"1": 0.0135, "2": 0.9465, "3": 0.04, "4": 0.0},
        "delta": {"1": 0.0, "2": 0.04, "3": 0.887, "4": 0.073},
        "beta": {"1": 0.0, "2": 0.0, "3": 0.073, "4": 0.927},
    }

    @pytest.mark.parametrize("team", TEAMS)
    def test_probabilities_sum_to_one(self, stability, team):
        probs = stability["rank_probability_matrix"][team]
        total = sum(probs.values())
        assert abs(total - 1.0) < 1e-6, (
            f"{team} rank probabilities sum to {total}, expected 1.0"
        )

    @pytest.mark.parametrize("team", TEAMS)
    def test_all_ranks_present(self, stability, team):
        probs = stability["rank_probability_matrix"][team]
        for r in range(1, len(TEAMS) + 1):
            assert str(r) in probs, (
                f"{team} missing rank {r} in probability matrix"
            )

    @pytest.mark.parametrize("team", TEAMS)
    def test_probabilities_non_negative(self, stability, team):
        probs = stability["rank_probability_matrix"][team]
        for rank, prob in probs.items():
            assert prob >= 0.0, (
                f"{team} rank {rank} has negative probability {prob}"
            )

    @pytest.mark.parametrize("team", TEAMS)
    def test_dominant_rank(self, stability, team):
        expected = self.EXPECTED_DOMINANT[team]
        actual = stability["dominant_rank"][team]
        assert actual == expected, (
            f"{team} dominant rank: expected {expected}, got {actual}"
        )

    @pytest.mark.parametrize("team", TEAMS)
    def test_rank_certainty(self, stability, team):
        expected = self.EXPECTED_CERTAINTY[team]
        actual = stability["rank_certainty"][team]
        assert abs(actual - expected) < ATOL_STAB, (
            f"{team} rank certainty: expected {expected:.4f}, got {actual:.4f}"
        )

    @pytest.mark.parametrize("team", TEAMS)
    def test_rank_probabilities_values(self, stability, team):
        """Check specific rank probability values."""
        expected_probs = self.EXPECTED_RANK_PROBS[team]
        actual_probs = stability["rank_probability_matrix"][team]
        for rank, expected in expected_probs.items():
            actual = actual_probs[rank]
            assert abs(actual - expected) < ATOL_STAB, (
                f"{team} P(rank={rank}): expected {expected:.4f}, got {actual:.4f}"
            )

    def test_gamma_dominant_first(self, stability):
        """Gamma should have the highest probability of rank 1."""
        gamma_rank1 = stability["rank_probability_matrix"]["gamma"]["1"]
        for team in TEAMS:
            if team != "gamma":
                other_rank1 = stability["rank_probability_matrix"][team]["1"]
                assert gamma_rank1 > other_rank1, (
                    f"gamma P(rank=1) should be highest but "
                    f"gamma={gamma_rank1:.4f} vs {team}={other_rank1:.4f}"
                )

    def test_rank_probability_columns_sum(self, stability):
        """Each rank column should sum to ~1.0 across teams."""
        for r in range(1, len(TEAMS) + 1):
            total = sum(
                stability["rank_probability_matrix"][t][str(r)]
                for t in TEAMS
            )
            assert abs(total - 1.0) < ATOL_STAB, (
                f"Rank {r} column sums to {total}, expected ~1.0"
            )


class TestPairwiseDominance:
    """Verify pairwise dominance probabilities."""

    EXPECTED_PAIRWISE = {
        ("gamma", "alpha"): 0.9865,
        ("gamma", "beta"): 1.0,
        ("gamma", "delta"): 1.0,
        ("alpha", "beta"): 1.0,
        ("alpha", "delta"): 0.96,
        ("delta", "beta"): 0.927,
    }

    def test_self_comparison_half(self, stability):
        for team in TEAMS:
            actual = stability["pairwise_dominance"][team][team]
            assert abs(actual - 0.5) < 1e-6, (
                f"P({team} > {team}) should be 0.5, got {actual}"
            )

    def test_symmetry(self, stability):
        """P(A > B) + P(B > A) should approximately equal 1.0."""
        for i, t1 in enumerate(TEAMS):
            for t2 in TEAMS[i+1:]:
                p_ab = stability["pairwise_dominance"][t1][t2]
                p_ba = stability["pairwise_dominance"][t2][t1]
                total = p_ab + p_ba
                assert abs(total - 1.0) < ATOL_STAB, (
                    f"P({t1}>{t2}) + P({t2}>{t1}) = {total}, expected ~1.0"
                )

    @pytest.mark.parametrize("pair,expected", list(EXPECTED_PAIRWISE.items()))
    def test_dominance_values(self, stability, pair, expected):
        t1, t2 = pair
        actual = stability["pairwise_dominance"][t1][t2]
        assert abs(actual - expected) < ATOL_STAB, (
            f"P({t1} > {t2}): expected {expected:.4f}, got {actual:.4f}"
        )

    def test_dominance_ordering(self, stability):
        """Higher-ranked teams should dominate lower-ranked ones."""
        pw = stability["pairwise_dominance"]
        assert pw["gamma"]["alpha"] > 0.5
        assert pw["gamma"]["delta"] > 0.5
        assert pw["gamma"]["beta"] > 0.5
        assert pw["alpha"]["delta"] > 0.5
        assert pw["alpha"]["beta"] > 0.5
        assert pw["delta"]["beta"] > 0.5


class TestTomlConfigUsed:
    """Verify the solution reads configuration from TOML."""

    def test_weights_from_config(self, results):
        """If weights are from config (0.25, 0.35, 0.40), the weighted score
        should match the formula exactly."""
        for team in TEAMS:
            ovr = results["teams"][team]["overall"]
            expected = (0.25 * ovr["segmentation_score"] +
                        0.35 * ovr["staging_score"] +
                        0.40 * ovr["prognosis_score"])
            assert abs(ovr["weighted_score"] - expected) < 1e-8
