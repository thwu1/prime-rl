
import json
import math
import os
import subprocess
import pytest


MODELS = ["alpha", "beta", "gamma"]
BENCHMARKS = ["fir_filter", "matrix_mult", "fft_radix2", "aes_encrypt", "jpeg_dct"]


@pytest.fixture(scope="session", autouse=True)
def run_analyzer():
    """Run the analyzer before tests if output doesn't exist."""
    output_path = "/app/output/analysis.json"
    analyzer_path = "/app/hls_analyzer.py"
    if os.path.exists(analyzer_path):
        result = subprocess.run(
            ["python3", analyzer_path],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            pytest.fail(
                f"hls_analyzer.py failed with code {result.returncode}:\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )


@pytest.fixture(scope="session")
def analysis():
    output_path = "/app/output/analysis.json"
    if not os.path.exists(output_path):
        pytest.fail(f"{output_path} not found. The analyzer must produce this file.")
    with open(output_path) as f:
        return json.load(f)


# ── Pass@K Tests ──


class TestPassAtK:
    """Verify the unbiased Pass@K estimator values."""

    def _pass_at_k(self, n, c, k):
        if n - c < k:
            return 1.0
        return 1.0 - math.comb(n - c, k) / math.comb(n, k)

    def test_output_has_pass_at_k(self, analysis):
        assert "pass_at_k" in analysis, "Missing 'pass_at_k' in output"
        for model in MODELS:
            assert model in analysis["pass_at_k"], f"Missing model '{model}' in pass_at_k"
            for k in ["1", "5", "10"]:
                assert k in analysis["pass_at_k"][model], f"Missing k={k} for {model}"
                for stage in ["compile", "simulate", "synthesize"]:
                    assert stage in analysis["pass_at_k"][model][k], (
                        f"Missing stage '{stage}' for {model} k={k}"
                    )

    def test_alpha_pass_at_1_compile(self, analysis):
        """alpha: compile pass counts [10,9,10,8,10] / n=10 each -> avg pass@1."""
        val = analysis["pass_at_k"]["alpha"]["1"]["compile"]
        expected = 0.94
        assert abs(val - expected) < 1e-6, f"Expected {expected}, got {val}"

    def test_alpha_pass_at_1_synthesize(self, analysis):
        """alpha: synth pass counts [6,5,4,3,7] / n=10 -> avg pass@1 = 0.5."""
        val = analysis["pass_at_k"]["alpha"]["1"]["synthesize"]
        expected = 0.5
        assert abs(val - expected) < 1e-6, f"Expected {expected}, got {val}"

    def test_beta_pass_at_1_synthesize(self, analysis):
        """beta: synth pass counts [6,8,5,7,4] / n=10 -> avg pass@1 = 0.6."""
        val = analysis["pass_at_k"]["beta"]["1"]["synthesize"]
        expected = 0.6
        assert abs(val - expected) < 1e-6, f"Expected {expected}, got {val}"

    def test_gamma_pass_at_1_simulate(self, analysis):
        """gamma: sim pass counts [6,7,5,6,8] / n=10 -> avg pass@1 = 0.64."""
        val = analysis["pass_at_k"]["gamma"]["1"]["simulate"]
        expected = 0.64
        assert abs(val - expected) < 1e-6, f"Expected {expected}, got {val}"

    def test_alpha_pass_at_5_synthesize(self, analysis):
        """alpha pass@5 synth: involves non-trivial binomial coefficients."""
        val = analysis["pass_at_k"]["alpha"]["5"]["synthesize"]
        benchmarks_c = [6, 5, 4, 3, 7]
        expected = sum(self._pass_at_k(10, c, 5) for c in benchmarks_c) / 5
        assert abs(val - expected) < 1e-6, f"Expected {expected:.10f}, got {val}"

    def test_pass_at_10_all_ones(self, analysis):
        """With n=10 and c>=1, pass@10 should always be 1.0."""
        for model in MODELS:
            for stage in ["compile", "simulate", "synthesize"]:
                val = analysis["pass_at_k"][model]["10"][stage]
                assert abs(val - 1.0) < 1e-9, (
                    f"{model} pass@10 {stage} should be 1.0, got {val}"
                )

    def test_pass_at_5_simulate_shared(self, analysis):
        """alpha and beta have identical sim pass counts, so pass@5 sim should match."""
        a = analysis["pass_at_k"]["alpha"]["5"]["simulate"]
        b = analysis["pass_at_k"]["beta"]["5"]["simulate"]
        assert abs(a - b) < 1e-9, (
            f"alpha and beta pass@5 simulate should be equal: {a} vs {b}"
        )


# ── Pareto Front Tests ──


class TestParetoFronts:
    """Verify Pareto-optimal design point identification."""

    def test_output_has_pareto_fronts(self, analysis):
        assert "pareto_fronts" in analysis
        for model in MODELS:
            assert model in analysis["pareto_fronts"]
            for bench in BENCHMARKS:
                assert bench in analysis["pareto_fronts"][model], (
                    f"Missing {bench} for {model}"
                )

    def test_alpha_fir_filter_front_size(self, analysis):
        """7 synthesis results in alpha/fir_filter; after constraint filtering, 4 Pareto-optimal."""
        front = analysis["pareto_fronts"]["alpha"]["fir_filter"]
        assert len(front) == 4, f"Expected 4 Pareto-optimal points, got {len(front)}"

    def test_alpha_fft_radix2_dominated_excluded(self, analysis):
        """Point (90, 22000, 160) in alpha/fft_radix2 is dominated by (35, 20000, 140)."""
        front = analysis["pareto_fronts"]["alpha"]["fft_radix2"]
        for pt in front:
            lat = pt["latency_ns"]
            area = pt["area_luts"]
            pwr = pt["power_mw"]
            assert not (
                abs(lat - 90.0) < 0.1
                and abs(area - 22000) < 1
                and abs(pwr - 160.0) < 0.1
            ), "Dominated point (90, 22000, 160) should not be in Pareto front"

    def test_alpha_fft_radix2_front_size(self, analysis):
        """alpha/fft_radix2: 5 synthesis results, 4 within constraints, 1 dominated -> 3 Pareto-optimal."""
        front = analysis["pareto_fronts"]["alpha"]["fft_radix2"]
        assert len(front) == 3, f"Expected 3, got {len(front)}"

    def test_beta_aes_dominated_excluded(self, analysis):
        """beta/aes_encrypt: point (90, 18000, 130) dominated by (18, 15500, 105)."""
        front = analysis["pareto_fronts"]["beta"]["aes_encrypt"]
        for pt in front:
            assert not (
                abs(pt["latency_ns"] - 90.0) < 0.1
                and abs(pt["area_luts"] - 18000) < 1
                and abs(pt["power_mw"] - 130.0) < 0.1
            ), "Dominated point (90, 18000, 130) should not be in Pareto front"

    def test_beta_aes_front_size(self, analysis):
        """beta/aes_encrypt: 7 points, 1 dominated -> 6 Pareto-optimal."""
        front = analysis["pareto_fronts"]["beta"]["aes_encrypt"]
        assert len(front) == 6, f"Expected 6, got {len(front)}"

    def test_alpha_jpeg_dct_all_nondominated(self, analysis):
        """alpha/jpeg_dct: all 7 points are non-dominated (verified by hand)."""
        front = analysis["pareto_fronts"]["alpha"]["jpeg_dct"]
        assert len(front) == 7, f"Expected 7, got {len(front)}"

    def test_gamma_jpeg_dct_front_size(self, analysis):
        """gamma/jpeg_dct: all 8 points are non-dominated."""
        front = analysis["pareto_fronts"]["gamma"]["jpeg_dct"]
        assert len(front) == 8, f"Expected 8, got {len(front)}"

    def test_pareto_sorted_by_latency(self, analysis):
        """All Pareto fronts must be sorted by ascending latency_ns."""
        for model in MODELS:
            for bench in analysis["pareto_fronts"][model]:
                front = analysis["pareto_fronts"][model][bench]
                latencies = [pt["latency_ns"] for pt in front]
                assert latencies == sorted(latencies), (
                    f"{model}/{bench} Pareto front not sorted by latency"
                )

    def test_specific_pareto_point_present(self, analysis):
        """The point (80.0, 4800, 30.0) in alpha/fir_filter must be on the front."""
        front = analysis["pareto_fronts"]["alpha"]["fir_filter"]
        found = any(
            abs(pt["latency_ns"] - 80.0) < 0.1
            and abs(pt["area_luts"] - 4800) < 1
            and abs(pt["power_mw"] - 30.0) < 0.1
            for pt in front
        )
        assert found, "Point (80.0, 4800, 30.0) should be on alpha/fir_filter front"

    def test_beta_matrix_mult_all_nondominated(self, analysis):
        """beta/matrix_mult: all 8 points form a staircase, all non-dominated."""
        front = analysis["pareto_fronts"]["beta"]["matrix_mult"]
        assert len(front) == 8, f"Expected 8, got {len(front)}"

    def test_constraints_applied(self, analysis):
        """Points violating resource constraints must be excluded before Pareto analysis."""
        assert len(analysis["pareto_fronts"]["alpha"]["fir_filter"]) == 4
        assert len(analysis["pareto_fronts"]["beta"]["fft_radix2"]) == 5


# ── Hypervolume Tests ──


class TestHypervolume:
    """Verify 3D hypervolume indicator computation."""

    def test_output_has_hypervolumes(self, analysis):
        assert "hypervolumes" in analysis
        for model in MODELS:
            assert model in analysis["hypervolumes"]
            assert "average" in analysis["hypervolumes"][model]

    def test_alpha_fir_filter_hypervolume(self, analysis):
        val = analysis["hypervolumes"]["alpha"]["fir_filter"]
        expected = 20830400000.0
        assert abs(val - expected) / expected < 0.001, (
            f"Expected ~{expected}, got {val}"
        )

    def test_alpha_matrix_mult_hypervolume(self, analysis):
        val = analysis["hypervolumes"]["alpha"]["matrix_mult"]
        expected = 16368400000.0
        assert abs(val - expected) / expected < 0.001, (
            f"Expected ~{expected}, got {val}"
        )

    def test_beta_aes_encrypt_hypervolume(self, analysis):
        val = analysis["hypervolumes"]["beta"]["aes_encrypt"]
        expected = 19463942500.0
        assert abs(val - expected) / expected < 0.001, (
            f"Expected ~{expected}, got {val}"
        )

    def test_gamma_fir_filter_hypervolume(self, analysis):
        val = analysis["hypervolumes"]["gamma"]["fir_filter"]
        expected = 21254162000.0
        assert abs(val - expected) / expected < 0.001, (
            f"Expected ~{expected}, got {val}"
        )

    def test_gamma_jpeg_dct_hypervolume(self, analysis):
        val = analysis["hypervolumes"]["gamma"]["jpeg_dct"]
        expected = 16919505000.0
        assert abs(val - expected) / expected < 0.001, (
            f"Expected ~{expected}, got {val}"
        )

    def test_alpha_average_hypervolume(self, analysis):
        expected_avg = 17593965500.0
        val = analysis["hypervolumes"]["alpha"]["average"]
        assert abs(val - expected_avg) / expected_avg < 0.001, (
            f"Expected ~{expected_avg}, got {val}"
        )

    def test_gamma_average_hypervolume(self, analysis):
        expected_avg = 18479928640.0
        val = analysis["hypervolumes"]["gamma"]["average"]
        assert abs(val - expected_avg) / expected_avg < 0.001, (
            f"Expected ~{expected_avg}, got {val}"
        )

    def test_hypervolume_ordering(self, analysis):
        """gamma should have highest average hypervolume, then beta, then alpha."""
        a = analysis["hypervolumes"]["alpha"]["average"]
        b = analysis["hypervolumes"]["beta"]["average"]
        g = analysis["hypervolumes"]["gamma"]["average"]
        assert g > b > a, f"Expected gamma > beta > alpha, got {g}, {b}, {a}"

    def test_per_benchmark_consistency(self, analysis):
        """Average hypervolume should equal mean of per-benchmark values."""
        for model in MODELS:
            hvs = [analysis["hypervolumes"][model][b] for b in BENCHMARKS]
            computed_avg = sum(hvs) / len(hvs)
            reported_avg = analysis["hypervolumes"][model]["average"]
            assert abs(computed_avg - reported_avg) < 1.0, (
                f"{model}: average mismatch {computed_avg} vs {reported_avg}"
            )


# ── Model Ranking Tests ──


class TestModelRanking:
    """Verify the composite ranking."""

    def test_output_has_ranking(self, analysis):
        assert "model_ranking" in analysis
        ranking = analysis["model_ranking"]
        assert len(ranking) == 3
        models_in_ranking = {r["model"] for r in ranking}
        assert models_in_ranking == {"alpha", "beta", "gamma"}

    def test_ranking_order(self, analysis):
        """beta should rank 1st, gamma 2nd, alpha 3rd."""
        ranking = analysis["model_ranking"]
        sorted_ranking = sorted(ranking, key=lambda r: r["rank"])
        assert sorted_ranking[0]["model"] == "beta", (
            f"Expected beta at rank 1, got {sorted_ranking[0]['model']}"
        )
        assert sorted_ranking[1]["model"] == "gamma", (
            f"Expected gamma at rank 2, got {sorted_ranking[1]['model']}"
        )
        assert sorted_ranking[2]["model"] == "alpha", (
            f"Expected alpha at rank 3, got {sorted_ranking[2]['model']}"
        )

    def test_ranking_has_composite_scores(self, analysis):
        for entry in analysis["model_ranking"]:
            assert "composite_score" in entry
            assert isinstance(entry["composite_score"], (int, float))
            assert 0.0 <= entry["composite_score"] <= 1.0

    def test_beta_composite_score(self, analysis):
        """beta composite = 0.5*0.6 + 0.3*0.7 + 0.2*(avg_hv/25e9)."""
        ranking = analysis["model_ranking"]
        beta = next(r for r in ranking if r["model"] == "beta")
        expected = 0.650872
        assert abs(beta["composite_score"] - expected) < 0.002, (
            f"Expected ~{expected}, got {beta['composite_score']}"
        )

    def test_alpha_composite_score(self, analysis):
        ranking = analysis["model_ranking"]
        alpha = next(r for r in ranking if r["model"] == "alpha")
        expected = 0.600752
        assert abs(alpha["composite_score"] - expected) < 0.002, (
            f"Expected ~{expected}, got {alpha['composite_score']}"
        )

    def test_composite_scores_descending(self, analysis):
        ranking = analysis["model_ranking"]
        scores = [r["composite_score"] for r in sorted(ranking, key=lambda r: r["rank"])]
        assert scores == sorted(scores, reverse=True), (
            "Composite scores should be in descending order by rank"
        )

    def test_ranks_are_1_2_3(self, analysis):
        ranks = sorted(r["rank"] for r in analysis["model_ranking"])
        assert ranks == [1, 2, 3], f"Ranks should be [1,2,3], got {ranks}"


# ── Hypervolume Cross-Validation Tests ──


class TestHypervolumeValidation:
    """Verify pymoo cross-validation of hypervolume computation."""

    def test_output_has_validation(self, analysis):
        assert "hypervolume_validation" in analysis, (
            "Missing 'hypervolume_validation' section"
        )

    def test_top_level_all_passed(self, analysis):
        hv_val = analysis["hypervolume_validation"]
        assert "all_passed" in hv_val
        assert hv_val["all_passed"] is True, (
            "Hypervolume cross-validation must pass for all model-benchmark pairs"
        )

    def test_per_model_structure(self, analysis):
        hv_val = analysis["hypervolume_validation"]
        for model in MODELS:
            assert model in hv_val, f"Missing model '{model}' in hypervolume_validation"
            for bench in BENCHMARKS:
                assert bench in hv_val[model], (
                    f"Missing {bench} for {model} in hypervolume_validation"
                )
                entry = hv_val[model][bench]
                assert "sweep_line" in entry, f"Missing sweep_line for {model}/{bench}"
                assert "pymoo" in entry, f"Missing pymoo for {model}/{bench}"
                assert "abs_diff" in entry, f"Missing abs_diff for {model}/{bench}"
                assert "passed" in entry, f"Missing passed for {model}/{bench}"

    def test_per_model_all_passed(self, analysis):
        hv_val = analysis["hypervolume_validation"]
        for model in MODELS:
            assert "all_passed" in hv_val[model], (
                f"Missing all_passed for {model}"
            )
            assert hv_val[model]["all_passed"] is True, (
                f"Cross-validation failed for model '{model}'"
            )

    def test_sweep_line_matches_hypervolumes(self, analysis):
        """sweep_line values in validation must match the hypervolumes section."""
        hv_val = analysis["hypervolume_validation"]
        hvs = analysis["hypervolumes"]
        for model in MODELS:
            for bench in BENCHMARKS:
                sweep = hv_val[model][bench]["sweep_line"]
                reported = hvs[model][bench]
                assert abs(sweep - reported) < 1.0, (
                    f"sweep_line {sweep} != hypervolumes {reported} for {model}/{bench}"
                )

    def test_pymoo_values_positive(self, analysis):
        """All pymoo hypervolume values should be positive."""
        hv_val = analysis["hypervolume_validation"]
        for model in MODELS:
            for bench in BENCHMARKS:
                pymoo_val = hv_val[model][bench]["pymoo"]
                assert pymoo_val > 0, (
                    f"pymoo HV should be positive for {model}/{bench}, got {pymoo_val}"
                )

    def test_relative_difference_within_tolerance(self, analysis):
        """All sweep_line vs pymoo differences should be < 0.1% relative."""
        hv_val = analysis["hypervolume_validation"]
        for model in MODELS:
            for bench in BENCHMARKS:
                entry = hv_val[model][bench]
                if entry["sweep_line"] > 0:
                    rel_diff = entry["abs_diff"] / entry["sweep_line"]
                    assert rel_diff < 0.001, (
                        f"Relative diff {rel_diff:.6f} too large for {model}/{bench}"
                    )


# ── Gnuplot Visualization Tests ──


class TestParetoPlots:
    """Verify gnuplot-generated Pareto front scatter plots."""

    def test_svg_files_exist(self):
        """One SVG file per model-benchmark pair must exist."""
        for model in MODELS:
            for bench in BENCHMARKS:
                svg_path = f"/app/output/plots/pareto_{model}_{bench}.svg"
                assert os.path.exists(svg_path), f"Missing SVG: {svg_path}"
                assert os.path.getsize(svg_path) > 100, (
                    f"SVG file too small: {svg_path}"
                )

    def test_dat_files_exist(self):
        """One .dat data file per model-benchmark pair must exist."""
        for model in MODELS:
            for bench in BENCHMARKS:
                dat_path = f"/app/output/plots/pareto_{model}_{bench}.dat"
                assert os.path.exists(dat_path), f"Missing data file: {dat_path}"

    def test_svg_contains_svg_tag(self):
        """SVG files must contain valid SVG markup."""
        svg_path = "/app/output/plots/pareto_alpha_fir_filter.svg"
        with open(svg_path) as f:
            content = f.read()
        assert "<svg" in content, "SVG file does not contain <svg> tag"

    def test_dat_file_point_count_alpha_fir(self):
        """alpha/fir_filter has 4 Pareto-optimal points; dat file should match."""
        dat_path = "/app/output/plots/pareto_alpha_fir_filter.dat"
        with open(dat_path) as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        assert len(lines) == 4, f"Expected 4 data lines, got {len(lines)}"

    def test_dat_file_point_count_beta_matrix(self):
        """beta/matrix_mult has 8 Pareto-optimal points; dat file should match."""
        dat_path = "/app/output/plots/pareto_beta_matrix_mult.dat"
        with open(dat_path) as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        assert len(lines) == 8, f"Expected 8 data lines, got {len(lines)}"

    def test_dat_file_has_three_columns(self):
        """Data files must have 3 numeric columns per line."""
        dat_path = "/app/output/plots/pareto_alpha_fir_filter.dat"
        with open(dat_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                assert len(parts) == 3, (
                    f"Expected 3 columns, got {len(parts)}: {line}"
                )
                for p in parts:
                    float(p)  # must be numeric

    def test_dat_file_specific_point(self):
        """The Pareto point (80.0, 4800, 30.0) should appear in alpha/fir_filter data."""
        dat_path = "/app/output/plots/pareto_alpha_fir_filter.dat"
        with open(dat_path) as f:
            content = f.read()
        assert "80.0" in content and "4800" in content and "30.0" in content, (
            "Point (80.0, 4800, 30.0) not found in alpha/fir_filter data file"
        )

    def test_all_fifteen_svgs(self):
        """All 15 model-benchmark SVGs must exist and be valid SVG."""
        count = 0
        for model in MODELS:
            for bench in BENCHMARKS:
                svg_path = f"/app/output/plots/pareto_{model}_{bench}.svg"
                assert os.path.exists(svg_path), f"Missing: {svg_path}"
                with open(svg_path) as f:
                    head = f.read(500)
                assert "<svg" in head or "<?xml" in head, (
                    f"{svg_path} does not look like valid SVG"
                )
                count += 1
        assert count == 15, f"Expected 15 SVG files, processed {count}"


# ── Ranking Sensitivity Analysis Tests ──


class TestRankingSensitivity:
    """Verify the weight-space ranking sensitivity analysis."""

    def test_output_has_sensitivity(self, analysis):
        assert "ranking_sensitivity" in analysis, (
            "Missing 'ranking_sensitivity' section"
        )

    def test_total_combinations(self, analysis):
        """Grid of 0.1-step weights with each >= 0.1 gives 36 valid combos."""
        sens = analysis["ranking_sensitivity"]
        assert "total_combinations" in sens
        assert sens["total_combinations"] == 36, (
            f"Expected 36 combinations, got {sens['total_combinations']}"
        )

    def test_ranking_counts_sum(self, analysis):
        """All ranking counts must sum to the total combinations."""
        sens = analysis["ranking_sensitivity"]
        assert "ranking_counts" in sens
        total = sum(sens["ranking_counts"].values())
        assert total == 36, f"Ranking counts sum to {total}, expected 36"

    def test_dominant_ranking_structure(self, analysis):
        """dominant_ranking should list all 3 models exactly once."""
        sens = analysis["ranking_sensitivity"]
        assert "dominant_ranking" in sens
        dom = sens["dominant_ranking"]
        assert len(dom) == 3, f"Expected 3 models, got {len(dom)}"
        assert set(dom) == {"alpha", "beta", "gamma"}, (
            f"Expected {{alpha, beta, gamma}}, got {set(dom)}"
        )

    def test_stability_fraction_valid(self, analysis):
        """stability_fraction must be between 0 and 1."""
        sens = analysis["ranking_sensitivity"]
        assert "stability_fraction" in sens
        frac = sens["stability_fraction"]
        assert 0.0 < frac <= 1.0, f"Invalid stability_fraction: {frac}"

    def test_stability_fraction_consistent(self, analysis):
        """stability_fraction must equal dominant_ranking count / total."""
        sens = analysis["ranking_sensitivity"]
        dom_key = ",".join(sens["dominant_ranking"])
        expected_frac = sens["ranking_counts"][dom_key] / sens["total_combinations"]
        assert abs(sens["stability_fraction"] - expected_frac) < 1e-9, (
            f"stability_fraction {sens['stability_fraction']} != "
            f"computed {expected_frac}"
        )

    def test_beta_always_beats_alpha(self, analysis):
        """Beta dominates alpha on all metrics; beta must rank above alpha in every combo."""
        sens = analysis["ranking_sensitivity"]
        for ranking_str, count in sens["ranking_counts"].items():
            models = ranking_str.split(",")
            beta_pos = models.index("beta")
            alpha_pos = models.index("alpha")
            assert beta_pos < alpha_pos, (
                f"Beta should always rank above alpha, but found: {ranking_str}"
            )

    def test_nominal_weights_in_counts(self, analysis):
        """At nominal weights (0.5, 0.3, 0.2) the ranking is beta > gamma > alpha."""
        sens = analysis["ranking_sensitivity"]
        assert "beta,gamma,alpha" in sens["ranking_counts"], (
            "Ranking 'beta,gamma,alpha' must appear (it's the nominal-weight result)"
        )
        assert sens["ranking_counts"]["beta,gamma,alpha"] > 0

    def test_multiple_rankings_exist(self, analysis):
        """The sensitivity analysis should find more than one distinct ranking."""
        sens = analysis["ranking_sensitivity"]
        assert len(sens["ranking_counts"]) >= 2, (
            "Expected at least 2 distinct rankings across weight space"
        )

    def test_ranking_counts_all_positive(self, analysis):
        """Every ranking count must be a positive integer."""
        sens = analysis["ranking_sensitivity"]
        for ranking_str, count in sens["ranking_counts"].items():
            assert isinstance(count, int), f"Count for {ranking_str} is not int"
            assert count > 0, f"Count for {ranking_str} is {count}"
