
import json
import os
import pytest

ANALYSIS_PATH = "/app/output/analysis.json"


@pytest.fixture(scope="module")
def analysis():
    assert os.path.isfile(ANALYSIS_PATH), f"Output file {ANALYSIS_PATH} does not exist"
    with open(ANALYSIS_PATH) as f:
        data = json.load(f)
    return data


def test_output_structure(analysis):
    """Verify the output JSON has all required top-level keys."""
    required_keys = ["scaled_pass1", "contamination_safe_scaled_pass1",
                     "paper_ablation_impact", "bootstrap_ci", "ranking",
                     "pairwise_significance", "jackknife_stability"]
    for key in required_keys:
        assert key in analysis, f"Missing top-level key: {key}"


def test_all_models_present(analysis):
    """Verify all 6 models appear in each per-model metric."""
    expected_models = {"aurora-72b", "blazeai-13b", "cognet-pro",
                       "deepmind-ultra", "etheron-7b", "frontier-max"}
    for key in ["scaled_pass1", "contamination_safe_scaled_pass1",
                "paper_ablation_impact", "bootstrap_ci",
                "jackknife_stability"]:
        actual = set(analysis[key].keys())
        assert actual == expected_models, f"{key}: expected {expected_models}, got {actual}"


class TestScaledPass1:
    """Verify line-weighted Scaled Pass@1 scores."""

    EXPECTED = {
        "aurora-72b": 0.351303,
        "blazeai-13b": 0.217430,
        "cognet-pro": 0.448787,
        "deepmind-ultra": 0.454178,
        "etheron-7b": 0.162624,
        "frontier-max": 0.465858,
    }

    @pytest.mark.parametrize("model_id,expected", list(EXPECTED.items()))
    def test_scaled_pass1(self, analysis, model_id, expected):
        actual = analysis["scaled_pass1"][model_id]
        assert abs(actual - expected) < 1e-4, \
            f"scaled_pass1[{model_id}]: expected {expected}, got {actual}"


class TestContaminationSafe:
    """Verify contamination-safe Scaled Pass@1 with proper date filtering."""

    EXPECTED = {
        "aurora-72b": 0.313395,
        "blazeai-13b": 0.192932,
        "cognet-pro": 0.507840,
        "deepmind-ultra": 0.446953,
        "etheron-7b": 0.267628,
    }

    @pytest.mark.parametrize("model_id,expected", list(EXPECTED.items()))
    def test_contamination_safe_scored(self, analysis, model_id, expected):
        actual = analysis["contamination_safe_scaled_pass1"][model_id]
        assert actual is not None, f"{model_id} should have a non-null score"
        assert abs(actual - expected) < 1e-4, \
            f"contamination_safe[{model_id}]: expected {expected}, got {actual}"

    def test_frontier_max_null(self, analysis):
        """frontier-max has cutoff 2025-02-15, all repos pre-date or match it, so score must be null."""
        val = analysis["contamination_safe_scaled_pass1"]["frontier-max"]
        assert val is None, f"frontier-max should be null (no safe snippets), got {val}"


class TestPaperAblation:
    """Verify paper ablation impact (with_paper - without_paper)."""

    EXPECTED = {
        "aurora-72b": 0.156783,
        "blazeai-13b": 0.099281,
        "cognet-pro": 0.206199,
        "deepmind-ultra": 0.295148,
        "etheron-7b": 0.071878,
        "frontier-max": 0.210692,
    }

    @pytest.mark.parametrize("model_id,expected", list(EXPECTED.items()))
    def test_ablation(self, analysis, model_id, expected):
        actual = analysis["paper_ablation_impact"][model_id]
        assert abs(actual - expected) < 1e-4, \
            f"ablation[{model_id}]: expected {expected}, got {actual}"

    def test_ablation_all_positive(self, analysis):
        """Paper context should help all models (positive ablation)."""
        for model_id, val in analysis["paper_ablation_impact"].items():
            assert val > 0, f"{model_id} ablation should be positive, got {val}"


class TestBootstrapCI:
    """Verify stratified bootstrap 95% CI bounds."""

    EXPECTED = {
        "aurora-72b": (0.24235, 0.465971),
        "blazeai-13b": (0.158112, 0.274237),
        "cognet-pro": (0.389149, 0.505145),
        "deepmind-ultra": (0.346102, 0.567038),
        "etheron-7b": (0.083835, 0.241032),
        "frontier-max": (0.340836, 0.599430),
    }

    @pytest.mark.parametrize("model_id,bounds", list(EXPECTED.items()))
    def test_ci_lower(self, analysis, model_id, bounds):
        expected_lower = bounds[0]
        actual = analysis["bootstrap_ci"][model_id]["lower"]
        assert abs(actual - expected_lower) < 1e-4, \
            f"CI lower[{model_id}]: expected {expected_lower}, got {actual}"

    @pytest.mark.parametrize("model_id,bounds", list(EXPECTED.items()))
    def test_ci_upper(self, analysis, model_id, bounds):
        expected_upper = bounds[1]
        actual = analysis["bootstrap_ci"][model_id]["upper"]
        assert abs(actual - expected_upper) < 1e-4, \
            f"CI upper[{model_id}]: expected {expected_upper}, got {actual}"

    @pytest.mark.parametrize("model_id", list(EXPECTED.keys()))
    def test_ci_contains_point_estimate(self, analysis, model_id):
        """The point estimate should fall within the CI."""
        lo = analysis["bootstrap_ci"][model_id]["lower"]
        hi = analysis["bootstrap_ci"][model_id]["upper"]
        point = analysis["scaled_pass1"][model_id]
        assert lo <= point <= hi, \
            f"{model_id}: point {point} not in [{lo}, {hi}]"


class TestRanking:
    """Verify model ranking by contamination-safe score."""

    def test_ranking_length(self, analysis):
        assert len(analysis["ranking"]) == 6

    def test_ranking_order(self, analysis):
        expected_order = ["cognet-pro", "deepmind-ultra", "aurora-72b",
                          "etheron-7b", "blazeai-13b", "frontier-max"]
        actual_order = [r["model_id"] for r in analysis["ranking"]]
        assert actual_order == expected_order, \
            f"Expected order {expected_order}, got {actual_order}"

    def test_ranking_ranks(self, analysis):
        expected_ranks = [1, 2, 3, 4, 5, None]
        actual_ranks = [r["rank"] for r in analysis["ranking"]]
        assert actual_ranks == expected_ranks, \
            f"Expected ranks {expected_ranks}, got {actual_ranks}"

    def test_frontier_max_last(self, analysis):
        """frontier-max (null score) should be ranked last with null rank."""
        last = analysis["ranking"][-1]
        assert last["model_id"] == "frontier-max"
        assert last["rank"] is None
        assert last["contamination_safe_score"] is None

    def test_ranking_scores_descending(self, analysis):
        """Non-null scores should be in descending order."""
        scores = [r["contamination_safe_score"] for r in analysis["ranking"]
                  if r["contamination_safe_score"] is not None]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], \
                f"Scores not descending at position {i}: {scores[i]} < {scores[i+1]}"


class TestPairwiseSignificance:
    """Verify pairwise statistical comparison with paired bootstrap and Bonferroni correction."""

    EXPECTED_SIGNIFICANT = {
        "blazeai-13b_vs_cognet-pro",
        "blazeai-13b_vs_deepmind-ultra",
        "blazeai-13b_vs_frontier-max",
        "cognet-pro_vs_etheron-7b",
        "deepmind-ultra_vs_etheron-7b",
        "etheron-7b_vs_frontier-max",
    }

    EXPECTED_NOT_SIGNIFICANT = {
        "aurora-72b_vs_blazeai-13b",
        "aurora-72b_vs_cognet-pro",
        "aurora-72b_vs_deepmind-ultra",
        "aurora-72b_vs_etheron-7b",
        "aurora-72b_vs_frontier-max",
        "blazeai-13b_vs_etheron-7b",
        "cognet-pro_vs_deepmind-ultra",
        "cognet-pro_vs_frontier-max",
        "deepmind-ultra_vs_frontier-max",
    }

    EXPECTED_CI = {
        "blazeai-13b_vs_cognet-pro": (-0.353236, -0.090493),
        "blazeai-13b_vs_deepmind-ultra": (-0.396377, -0.06813),
        "blazeai-13b_vs_frontier-max": (-0.519126, -0.013284),
        "cognet-pro_vs_etheron-7b": (0.149082, 0.450046),
        "deepmind-ultra_vs_etheron-7b": (0.04065, 0.527652),
        "etheron-7b_vs_frontier-max": (-0.48331, -0.197793),
    }

    def test_pair_count(self, analysis):
        """Should have C(6,2) = 15 pairs."""
        assert len(analysis["pairwise_significance"]) == 15

    def test_significant_count(self, analysis):
        """Exactly 6 pairs should be significant after Bonferroni correction."""
        sig = {k for k, v in analysis["pairwise_significance"].items() if v["significant"]}
        assert len(sig) == 6, f"Expected 6 significant pairs, got {len(sig)}: {sig}"

    @pytest.mark.parametrize("pair_key", list(EXPECTED_SIGNIFICANT))
    def test_significant_pairs(self, analysis, pair_key):
        entry = analysis["pairwise_significance"][pair_key]
        assert entry["significant"] is True, \
            f"{pair_key} should be significant, got CI=[{entry['ci_lower']}, {entry['ci_upper']}]"

    @pytest.mark.parametrize("pair_key", list(EXPECTED_NOT_SIGNIFICANT))
    def test_not_significant_pairs(self, analysis, pair_key):
        entry = analysis["pairwise_significance"][pair_key]
        assert entry["significant"] is False, \
            f"{pair_key} should NOT be significant, got CI=[{entry['ci_lower']}, {entry['ci_upper']}]"

    @pytest.mark.parametrize("pair_key,bounds", list(EXPECTED_CI.items()))
    def test_significant_ci_lower(self, analysis, pair_key, bounds):
        actual = analysis["pairwise_significance"][pair_key]["ci_lower"]
        assert abs(actual - bounds[0]) < 1e-4, \
            f"{pair_key} ci_lower: expected {bounds[0]}, got {actual}"

    @pytest.mark.parametrize("pair_key,bounds", list(EXPECTED_CI.items()))
    def test_significant_ci_upper(self, analysis, pair_key, bounds):
        actual = analysis["pairwise_significance"][pair_key]["ci_upper"]
        assert abs(actual - bounds[1]) < 1e-4, \
            f"{pair_key} ci_upper: expected {bounds[1]}, got {actual}"

    def test_pair_key_format(self, analysis):
        """Pair keys should be alphabetically ordered model IDs joined by _vs_."""
        for key in analysis["pairwise_significance"]:
            parts = key.split("_vs_")
            assert len(parts) == 2, f"Invalid pair key format: {key}"
            assert parts[0] < parts[1], f"Pair key not alphabetically ordered: {key}"

    def test_pair_entry_structure(self, analysis):
        """Each entry must have model_a, model_b, ci_lower, ci_upper, significant."""
        for key, entry in analysis["pairwise_significance"].items():
            assert "model_a" in entry
            assert "model_b" in entry
            assert "ci_lower" in entry
            assert "ci_upper" in entry
            assert "significant" in entry
            assert isinstance(entry["significant"], bool)


class TestJackknifeStability:
    """Verify leave-one-paper-out jackknife analysis."""

    EXPECTED_SE = {
        "aurora-72b": 0.062308,
        "blazeai-13b": 0.031070,
        "cognet-pro": 0.031212,
        "deepmind-ultra": 0.061871,
        "etheron-7b": 0.043490,
        "frontier-max": 0.071242,
    }

    EXPECTED_INFLUENTIAL = {
        "aurora-72b": ("optisteps", 0.041196),
        "blazeai-13b": ("dyntoken", 0.018814),
        "cognet-pro": ("diffusiondpo", 0.022155),
        "deepmind-ultra": ("gridiso", 0.040002),
        "etheron-7b": ("gridiso", 0.033523),
        "frontier-max": ("repae", 0.049965),
    }

    EXPECTED_LOO_AURORA = {
        "diffusiondpo": 0.369238,
        "diffxformer": 0.313395,
        "dyntoken": 0.353357,
        "fracgen": 0.334012,
        "gridiso": 0.355026,
        "optisteps": 0.392499,
        "repae": 0.329205,
        "schedfree": 0.364562,
    }

    @pytest.mark.parametrize("model_id,expected_se", list(EXPECTED_SE.items()))
    def test_jackknife_se(self, analysis, model_id, expected_se):
        actual = analysis["jackknife_stability"][model_id]["jackknife_se"]
        assert abs(actual - expected_se) < 1e-4, \
            f"jackknife_se[{model_id}]: expected {expected_se}, got {actual}"

    @pytest.mark.parametrize("model_id,expected", list(EXPECTED_INFLUENTIAL.items()))
    def test_most_influential_paper(self, analysis, model_id, expected):
        expected_paper, expected_magnitude = expected
        entry = analysis["jackknife_stability"][model_id]
        assert entry["most_influential_paper"] == expected_paper, \
            f"{model_id}: expected most influential '{expected_paper}', got '{entry['most_influential_paper']}'"
        assert abs(entry["influence_magnitude"] - expected_magnitude) < 1e-4, \
            f"{model_id}: expected influence {expected_magnitude}, got {entry['influence_magnitude']}"

    @pytest.mark.parametrize("paper_id,expected_score", list(EXPECTED_LOO_AURORA.items()))
    def test_aurora_loo_scores(self, analysis, paper_id, expected_score):
        actual = analysis["jackknife_stability"]["aurora-72b"]["leave_one_out_scores"][paper_id]
        assert abs(actual - expected_score) < 1e-4, \
            f"aurora LOO-{paper_id}: expected {expected_score}, got {actual}"

    def test_loo_scores_have_all_papers(self, analysis):
        """Each model's leave_one_out_scores should have all 8 papers."""
        expected_papers = {"diffxformer", "diffusiondpo", "dyntoken", "optisteps",
                           "fracgen", "schedfree", "gridiso", "repae"}
        for model_id in self.EXPECTED_SE:
            actual = set(analysis["jackknife_stability"][model_id]["leave_one_out_scores"].keys())
            assert actual == expected_papers, \
                f"{model_id}: expected papers {expected_papers}, got {actual}"

    def test_se_positive(self, analysis):
        """All jackknife SEs should be positive."""
        for model_id in self.EXPECTED_SE:
            se = analysis["jackknife_stability"][model_id]["jackknife_se"]
            assert se > 0, f"{model_id}: SE should be positive, got {se}"

    def test_entry_structure(self, analysis):
        """Each entry must have jackknife_se, most_influential_paper, influence_magnitude, leave_one_out_scores."""
        for model_id, entry in analysis["jackknife_stability"].items():
            assert "jackknife_se" in entry
            assert "most_influential_paper" in entry
            assert "influence_magnitude" in entry
            assert "leave_one_out_scores" in entry
            assert isinstance(entry["leave_one_out_scores"], dict)
