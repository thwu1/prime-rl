"""Tests for SMT-COMP 2026 Scoring Engine output.

"""

import json
import math
import os
import pytest

OUTPUT_PATH = "/app/output.json"


@pytest.fixture(scope="module")
def output():
    assert os.path.exists(OUTPUT_PATH), f"Output file {OUTPUT_PATH} does not exist"
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    return data


# ============================================================
# STRUCTURAL TESTS
# ============================================================

class TestStructure:
    def test_top_level_keys(self, output):
        required = {"disagreement_removals", "divisions", "derived_eligibility",
                     "best_overall", "biggest_lead", "largest_contribution"}
        assert required.issubset(set(output.keys())), \
            f"Missing keys: {required - set(output.keys())}"

    def test_divisions_present(self, output):
        assert "QF_BV" in output["divisions"]
        assert "QF_LIA" in output["divisions"]
        assert "QF_UF" in output["divisions"]

    def test_division_subkeys(self, output):
        for div_name in ["QF_BV", "QF_LIA", "QF_UF"]:
            div = output["divisions"][div_name]
            assert "num_benchmarks" in div
            assert "parallel" in div
            assert "sequential" in div
            assert "par2" in div
            assert "parallel_ranking" in div
            assert "sequential_ranking" in div

    def test_best_overall_subkeys(self, output):
        assert "parallel" in output["best_overall"]
        assert "sequential" in output["best_overall"]
        for mode in ("parallel", "sequential"):
            assert "scores" in output["best_overall"][mode]
            assert "ranking" in output["best_overall"][mode]

    def test_biggest_lead_subkeys(self, output):
        for mode in ("parallel", "sequential"):
            bl = output["biggest_lead"][mode]
            assert "divisions" in bl
            assert "overall_winner" in bl
            assert "overall_division" in bl

    def test_largest_contribution_subkeys(self, output):
        for mode in ("parallel", "sequential"):
            lc = output["largest_contribution"][mode]
            assert "divisions" in lc
            assert "overall_winner" in lc


# ============================================================
# DISAGREEMENT REMOVAL TESTS
# ============================================================

class TestDisagreementRemoval:
    def test_bv004_removed(self, output):
        """bv_004 has unknown status; alpha says sat, beta says unsat, both sound -> remove."""
        removals = output["disagreement_removals"]["QF_BV"]
        assert "bv_004" in removals, \
            "bv_004 should be removed: sound solvers alpha (sat) and beta (unsat) disagree"

    def test_lia004_not_removed(self, output):
        """lia_004 has unknown status but all sound solvers agree (all say sat) -> keep."""
        removals = output["disagreement_removals"]["QF_LIA"]
        assert "lia_004" not in removals, \
            "lia_004 should NOT be removed: no disagreement among sound solvers"

    def test_qf_uf_no_removals(self, output):
        """QF_UF has no unknown-status benchmarks, so no removals."""
        removals = output["disagreement_removals"]["QF_UF"]
        assert len(removals) == 0

    def test_qf_bv_benchmark_count(self, output):
        """QF_BV: 5 benchmarks - 1 removed = 4 used."""
        assert output["divisions"]["QF_BV"]["num_benchmarks"] == 4

    def test_qf_lia_benchmark_count(self, output):
        """QF_LIA: all 7 benchmarks kept."""
        assert output["divisions"]["QF_LIA"]["num_benchmarks"] == 7

    def test_qf_uf_benchmark_count(self, output):
        """QF_UF: all 6 benchmarks kept."""
        assert output["divisions"]["QF_UF"]["num_benchmarks"] == 6


# ============================================================
# PARALLEL DIVISION SCORE TESTS
# ============================================================

class TestParallelScores:
    def test_alpha_qf_bv(self, output):
        """alpha solves all 4 QF_BV benchmarks correctly."""
        s = output["divisions"]["QF_BV"]["parallel"]["alpha"]
        assert s["errors"] == 0
        assert s["correct"] == 4
        assert abs(s["wallclock"] - 191.2) < 0.01
        assert abs(s["cpu"] - 702.9) < 0.01

    def test_gamma_qf_bv_error(self, output):
        """gamma has 1 error in QF_BV (wrong answer on bv_003)."""
        s = output["divisions"]["QF_BV"]["parallel"]["gamma"]
        assert s["errors"] == 1, "gamma returns unsat on sat benchmark bv_003 -> error"
        assert s["correct"] == 3

    def test_beta_qf_bv(self, output):
        """beta solves 3 QF_BV benchmarks (timeout on bv_005)."""
        s = output["divisions"]["QF_BV"]["parallel"]["beta"]
        assert s["errors"] == 0
        assert s["correct"] == 3
        assert abs(s["wallclock"] - 105.2) < 0.01

    def test_beta_delta_qf_bv(self, output):
        """beta-delta solves all 4 QF_BV benchmarks."""
        s = output["divisions"]["QF_BV"]["parallel"]["beta-delta"]
        assert s["errors"] == 0
        assert s["correct"] == 4
        assert abs(s["wallclock"] - 194.2) < 0.01

    def test_epsilon_qf_bv(self, output):
        """epsilon solves 3 QF_BV (unknown on bv_002)."""
        s = output["divisions"]["QF_BV"]["parallel"]["epsilon"]
        assert s["errors"] == 0
        assert s["correct"] == 3

    def test_beta_delta_qf_lia(self, output):
        """beta-delta solves all 7 QF_LIA benchmarks."""
        s = output["divisions"]["QF_LIA"]["parallel"]["beta-delta"]
        assert s["errors"] == 0
        assert s["correct"] == 7
        assert abs(s["wallclock"] - 363.0) < 0.01

    def test_gamma_qf_lia(self, output):
        """gamma solves 6/7 in QF_LIA (unknown on idl_002)."""
        s = output["divisions"]["QF_LIA"]["parallel"]["gamma"]
        assert s["errors"] == 0
        assert s["correct"] == 6

    def test_gamma_qf_uf(self, output):
        """gamma solves all 6 QF_UF benchmarks."""
        s = output["divisions"]["QF_UF"]["parallel"]["gamma"]
        assert s["errors"] == 0
        assert s["correct"] == 6
        assert abs(s["wallclock"] - 354.0) < 0.01

    def test_beta_qf_uf(self, output):
        """beta solves 5/6 in QF_UF (timeout on uf_005)."""
        s = output["divisions"]["QF_UF"]["parallel"]["beta"]
        assert s["errors"] == 0
        assert s["correct"] == 5

    def test_epsilon_not_in_qf_uf(self, output):
        """epsilon does not enter QF_UF."""
        assert "epsilon" not in output["divisions"]["QF_UF"]["parallel"]


# ============================================================
# SEQUENTIAL SCORE TESTS
# ============================================================

class TestSequentialScores:
    def test_epsilon_sequential_drop(self, output):
        """epsilon's sequential correct count in QF_BV should be less than parallel
        because bv_005 cpu_time=1350 > T=1200."""
        par_n = output["divisions"]["QF_BV"]["parallel"]["epsilon"]["correct"]
        seq_n = output["divisions"]["QF_BV"]["sequential"]["epsilon"]["correct"]
        assert seq_n < par_n, \
            f"epsilon sequential correct ({seq_n}) should be < parallel ({par_n})"
        assert seq_n == 2
        assert par_n == 3

    def test_alpha_sequential_unchanged(self, output):
        """alpha's sequential score in QF_BV matches parallel (all cpu < T)."""
        par = output["divisions"]["QF_BV"]["parallel"]["alpha"]
        seq = output["divisions"]["QF_BV"]["sequential"]["alpha"]
        assert seq["correct"] == par["correct"]
        assert seq["errors"] == par["errors"]

    def test_sequential_cpu_value(self, output):
        """epsilon sequential CPU in QF_BV: only bv_001 and bv_003 contribute."""
        seq = output["divisions"]["QF_BV"]["sequential"]["epsilon"]
        # bv_001: ct=75.4, bv_003: ct=34.2 -> total = 109.6
        assert abs(seq["cpu"] - 109.6) < 0.01


# ============================================================
# PAR-2 SCORE TESTS
# ============================================================

class TestPAR2Scores:
    def test_alpha_qf_bv_par2(self, output):
        """alpha solves all QF_BV -> PAR-2 = regular wall time."""
        p2 = output["divisions"]["QF_BV"]["par2"]["alpha"]
        assert abs(p2["wallclock"] - 191.2) < 0.01

    def test_beta_qf_bv_par2(self, output):
        """beta has bv_005 unsolved -> PAR-2 penalty of 2*1200=2400."""
        p2 = output["divisions"]["QF_BV"]["par2"]["beta"]
        # 15.3 + 82.1 + 7.8 + 2400 = 2505.2
        assert abs(p2["wallclock"] - 2505.2) < 0.01

    def test_gamma_qf_bv_par2(self, output):
        """gamma has bv_003 error -> penalty 2*1200=2400."""
        p2 = output["divisions"]["QF_BV"]["par2"]["gamma"]
        # 8.2 + 48.9 + 2400 + 95.6 = 2552.7
        assert abs(p2["wallclock"] - 2552.7) < 0.01

    def test_beta_delta_qf_lia_par2(self, output):
        """beta-delta solves all QF_LIA -> PAR-2 = regular time."""
        p2 = output["divisions"]["QF_LIA"]["par2"]["beta-delta"]
        assert abs(p2["wallclock"] - 363.0) < 0.01

    def test_gamma_qf_uf_par2(self, output):
        """gamma solves all QF_UF -> PAR-2 = regular time."""
        p2 = output["divisions"]["QF_UF"]["par2"]["gamma"]
        assert abs(p2["wallclock"] - 354.0) < 0.01

    def test_beta_qf_uf_par2(self, output):
        """beta has uf_005 unsolved -> penalty."""
        p2 = output["divisions"]["QF_UF"]["par2"]["beta"]
        # 8 + 75 + 15 + 250 + 2400 + 110 = 2858
        assert abs(p2["wallclock"] - 2858.0) < 0.01


# ============================================================
# RANKING TESTS
# ============================================================

class TestRankings:
    def test_qf_bv_parallel_ranking(self, output):
        r = output["divisions"]["QF_BV"]["parallel_ranking"]
        assert r[0] == "alpha"
        assert r[1] == "beta-delta"
        assert r[2] == "beta"
        assert r[-1] == "gamma"

    def test_qf_lia_parallel_ranking(self, output):
        r = output["divisions"]["QF_LIA"]["parallel_ranking"]
        assert r[0] == "beta-delta"
        assert r[1] == "beta"
        assert r[2] == "alpha"

    def test_qf_uf_parallel_ranking(self, output):
        r = output["divisions"]["QF_UF"]["parallel_ranking"]
        assert r[0] == "gamma"
        assert r[1] == "beta-delta"
        assert r[2] == "alpha"
        assert r[3] == "beta"

    def test_qf_bv_sequential_ranking_top(self, output):
        r = output["divisions"]["QF_BV"]["sequential_ranking"]
        assert r[0] == "alpha"
        assert r[1] == "beta-delta"


# ============================================================
# DERIVED SOLVER ELIGIBILITY TESTS
# ============================================================

class TestDerivedEligibility:
    def test_beta_delta_exists(self, output):
        assert "beta-delta" in output["derived_eligibility"]

    def test_beta_delta_qf_bv_eligible(self, output):
        """beta-delta in QF_BV: PAR-2 improvement ~92% (194.2 vs 2505.2) -> eligible."""
        elig = output["derived_eligibility"]["beta-delta"]["QF_BV"]
        assert elig["eligible"] is True
        assert elig["improvement_pct"] > 90.0

    def test_beta_delta_qf_lia_not_eligible(self, output):
        """beta-delta in QF_LIA: PAR-2 improvement ~8.1% (363 vs 395) -> NOT eligible."""
        elig = output["derived_eligibility"]["beta-delta"]["QF_LIA"]
        assert elig["eligible"] is False
        assert elig["improvement_pct"] < 10.0

    def test_beta_delta_qf_uf_eligible(self, output):
        """beta-delta in QF_UF: PAR-2 improvement ~86.5% (385 vs 2858) -> eligible."""
        elig = output["derived_eligibility"]["beta-delta"]["QF_UF"]
        assert elig["eligible"] is True
        assert elig["improvement_pct"] > 80.0

    def test_beta_delta_competition_wide(self, output):
        """beta-delta eligible in at least one division -> competition_wide=True."""
        assert output["derived_eligibility"]["beta-delta"]["competition_wide"] is True


# ============================================================
# BEST OVERALL RANKING TESTS
# ============================================================

class TestBestOverall:
    def test_parallel_ranking_top(self, output):
        """Parallel best overall: beta-delta and alpha tied, beta-delta wins tiebreak."""
        r = output["best_overall"]["parallel"]["ranking"]
        assert r[0] == "beta-delta", f"Expected beta-delta first, got {r[0]}"
        assert r[1] == "alpha", f"Expected alpha second, got {r[1]}"

    def test_parallel_ranking_order(self, output):
        """Full parallel ranking: beta-delta, alpha, beta, epsilon, gamma."""
        r = output["best_overall"]["parallel"]["ranking"]
        assert r == ["beta-delta", "alpha", "beta", "epsilon", "gamma"]

    def test_parallel_scores_alpha(self, output):
        """alpha overall score: sum of nn_D * log10(N_D) across 3 divisions."""
        scores = output["best_overall"]["parallel"]["scores"]
        # (4/4)^2 * log10(4) + (7/7)^2 * log10(7) + (6/6)^2 * log10(6)
        expected = math.log10(4) + math.log10(7) + math.log10(6)
        assert abs(scores["alpha"] - expected) < 0.001

    def test_parallel_scores_gamma(self, output):
        """gamma has error in QF_BV -> nn=-2, dragging score down."""
        scores = output["best_overall"]["parallel"]["scores"]
        assert scores["gamma"] < 1.0, "gamma should have low score due to QF_BV error penalty"
        # -2*log10(4) + (6/7)^2*log10(7) + 1.0*log10(6)
        expected = -2 * math.log10(4) + (6/7)**2 * math.log10(7) + math.log10(6)
        assert abs(scores["gamma"] - expected) < 0.001

    def test_sequential_epsilon_lower(self, output):
        """epsilon's sequential overall score should be lower than parallel."""
        par_score = output["best_overall"]["parallel"]["scores"]["epsilon"]
        seq_score = output["best_overall"]["sequential"]["scores"]["epsilon"]
        assert seq_score < par_score

    def test_sequential_ranking(self, output):
        """Sequential ranking should still have beta-delta and alpha on top."""
        r = output["best_overall"]["sequential"]["ranking"]
        assert r[0] == "beta-delta"
        assert r[1] == "alpha"


# ============================================================
# BIGGEST LEAD TESTS
# ============================================================

class TestBiggestLead:
    def test_parallel_divisions(self, output):
        bl = output["biggest_lead"]["parallel"]["divisions"]
        assert "QF_BV" in bl
        assert "QF_LIA" in bl
        assert "QF_UF" in bl

    def test_parallel_qf_bv_winner(self, output):
        bl = output["biggest_lead"]["parallel"]["divisions"]["QF_BV"]
        assert bl["winner"] == "alpha"

    def test_parallel_qf_lia_winner(self, output):
        bl = output["biggest_lead"]["parallel"]["divisions"]["QF_LIA"]
        assert bl["winner"] == "beta-delta"

    def test_parallel_qf_uf_winner(self, output):
        bl = output["biggest_lead"]["parallel"]["divisions"]["QF_UF"]
        assert bl["winner"] == "gamma"

    def test_parallel_overall_winner(self, output):
        bl = output["biggest_lead"]["parallel"]
        assert bl["overall_winner"] == "beta-delta"
        assert bl["overall_division"] == "QF_LIA"

    def test_correctness_ranks_all_one(self, output):
        """All divisions have correctness_rank=1.0 (ties at top in each division)."""
        for div in ["QF_BV", "QF_LIA", "QF_UF"]:
            cr = output["biggest_lead"]["parallel"]["divisions"][div]["correctness_rank"]
            assert abs(cr - 1.0) < 0.001

    def test_parallel_wallclock_rank_positive(self, output):
        for div in ["QF_BV", "QF_LIA", "QF_UF"]:
            wr = output["biggest_lead"]["parallel"]["divisions"][div]["wallclock_rank"]
            assert wr >= 1.0


# ============================================================
# LARGEST CONTRIBUTION TESTS
# ============================================================

class TestLargestContribution:
    def test_parallel_divisions_exist(self, output):
        lc = output["largest_contribution"]["parallel"]["divisions"]
        assert len(lc) >= 2, "At least 2 divisions should be included"

    def test_parallel_overall_winner(self, output):
        lc = output["largest_contribution"]["parallel"]
        assert lc["overall_winner"] is not None

    def test_qf_bv_alpha_has_wallclock_contribution(self, output):
        """alpha contributes wallclock time improvement in QF_BV VBS."""
        lc = output["largest_contribution"]["parallel"]["divisions"]
        if "QF_BV" in lc and "alpha" in lc["QF_BV"]:
            wr = lc["QF_BV"]["alpha"]["wallclock_rank"]
            assert wr > 0, "alpha should have positive VBS wallclock contribution in QF_BV"

    def test_qf_bv_beta_no_contribution(self, output):
        """beta has 0 correctness contribution in QF_BV."""
        lc = output["largest_contribution"]["parallel"]["divisions"]
        if "QF_BV" in lc and "beta" in lc["QF_BV"]:
            cr = lc["QF_BV"]["beta"]["correctness_rank"]
            assert cr == 0.0

    def test_correctness_ranks_nonnegative(self, output):
        for mode in ("parallel", "sequential"):
            lc = output["largest_contribution"][mode]["divisions"]
            for div, solvers_data in lc.items():
                for solver, ranks in solvers_data.items():
                    assert ranks["correctness_rank"] >= 0

    def test_normalized_values_small(self, output):
        """Normalized values should be between 0 and 1."""
        lc = output["largest_contribution"]["parallel"]["divisions"]
        for div, solvers_data in lc.items():
            for solver, ranks in solvers_data.items():
                assert 0 <= ranks["normalized_correctness"] <= 1.0
                assert 0 <= ranks["normalized_wallclock"] <= 1.0


# ============================================================
# CROSS-VALIDATION TESTS
# ============================================================

class TestCrossValidation:
    def test_par2_penalty_consistency(self, output):
        """PAR-2 wallclock should always be >= regular wallclock."""
        for div in ["QF_BV", "QF_LIA", "QF_UF"]:
            par = output["divisions"][div]["parallel"]
            p2 = output["divisions"][div]["par2"]
            for solver in par:
                assert p2[solver]["wallclock"] >= par[solver]["wallclock"], \
                    f"PAR-2 should be >= regular wallclock for {solver} in {div}"

    def test_ranking_length_matches_solvers(self, output):
        for div in ["QF_BV", "QF_LIA", "QF_UF"]:
            par_solvers = set(output["divisions"][div]["parallel"].keys())
            par_ranking = set(output["divisions"][div]["parallel_ranking"])
            assert par_solvers == par_ranking, \
                f"Ranking mismatch in {div}: {par_solvers} vs {par_ranking}"

    def test_sequential_correct_leq_parallel(self, output):
        for div in ["QF_BV", "QF_LIA", "QF_UF"]:
            par = output["divisions"][div]["parallel"]
            seq = output["divisions"][div]["sequential"]
            for solver in par:
                assert seq[solver]["correct"] <= par[solver]["correct"], \
                    f"Sequential correct > parallel for {solver} in {div}"

    def test_best_overall_ranking_complete(self, output):
        """Best overall ranking should include all 5 solvers."""
        for mode in ("parallel", "sequential"):
            r = output["best_overall"][mode]["ranking"]
            assert len(r) == 5, f"Expected 5 solvers in {mode} ranking, got {len(r)}"

    def test_error_solver_ranked_last_in_division(self, output):
        """gamma has errors in QF_BV, should be ranked last there."""
        r = output["divisions"]["QF_BV"]["parallel_ranking"]
        assert r[-1] == "gamma"
