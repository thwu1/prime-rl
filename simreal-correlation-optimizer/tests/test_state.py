
import csv
import json
import os
import sqlite3

import numpy as np
import pytest
from scipy import stats

RESULTS_PATH = "/app/results.json"


@pytest.fixture(scope="session")
def evaluation_data():
    """Load evaluation data from CSV files and SQLite database."""
    conn = sqlite3.connect("/app/data/experiment.db")
    c = conn.cursor()
    c.execute("SELECT variant_name FROM variant_info ORDER BY variant_id")
    variants = [row[0] for row in c.fetchall()]
    conn.close()

    sim_results = {}
    policies_ordered = []
    tasks_ordered = []

    for variant in variants:
        with open(f"/app/data/sim/{variant}.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pol = row["policy"]
                tsk = row["task"]
                rate = float(row["success_rate"])
                sim_results.setdefault(pol, {}).setdefault(tsk, {})[variant] = rate
                if pol not in policies_ordered:
                    policies_ordered.append(pol)
                if tsk not in tasks_ordered:
                    tasks_ordered.append(tsk)

    real_results = {}
    with open("/app/data/real_results.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            real_results.setdefault(row["policy"], {})[row["task"]] = float(
                row["success_rate"]
            )

    return {
        "metadata": {
            "policies": policies_ordered,
            "tasks": tasks_ordered,
            "variants": variants,
        },
        "sim_results": sim_results,
        "real_results": real_results,
    }


@pytest.fixture(scope="session")
def results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


class TestOutputStructure:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json not found"

    def test_required_keys(self, results):
        required = [
            "mmrv_scores",
            "real_mean_scores",
            "task_correlations",
            "fisher_z_mean_r",
            "anova_eta_squared",
            "anova_f_stats",
            "deming_calibration",
            "influence_diagnostics",
            "permutation_p_value",
            "conformal_intervals",
            "aggregate_pearson_r",
        ]
        for key in required:
            assert key in results, f"Missing key: {key}"

    def test_all_policies_present(self, results, evaluation_data):
        for p in evaluation_data["metadata"]["policies"]:
            assert p in results["mmrv_scores"], f"Missing {p} in mmrv_scores"
            assert p in results["real_mean_scores"], f"Missing {p} in real_mean_scores"
            assert (
                p in results["influence_diagnostics"]
            ), f"Missing {p} in influence_diagnostics"
            assert (
                p in results["conformal_intervals"]
            ), f"Missing {p} in conformal_intervals"

    def test_all_tasks_in_correlations(self, results, evaluation_data):
        for t in evaluation_data["metadata"]["tasks"]:
            assert t in results["task_correlations"], f"Missing {t} in task_correlations"

    def test_all_variants_in_deming(self, results, evaluation_data):
        for v in evaluation_data["metadata"]["variants"]:
            assert v in results["deming_calibration"], f"Missing {v} in deming_calibration"
            assert "slope" in results["deming_calibration"][v]
            assert "intercept" in results["deming_calibration"][v]


class TestMMRV:
    """MMRV values are deterministic: max over variants, then mean over tasks."""

    def test_mmrv_rt1(self, results):
        assert abs(results["mmrv_scores"]["RT-1"] - 0.632) < 1e-3

    def test_mmrv_rt1x(self, results):
        assert abs(results["mmrv_scores"]["RT-1-X"] - 0.692) < 1e-3

    def test_mmrv_octo_base(self, results):
        assert abs(results["mmrv_scores"]["Octo-Base"] - 0.416) < 1e-3

    def test_mmrv_octo_small(self, results):
        assert abs(results["mmrv_scores"]["Octo-Small"] - 0.360) < 1e-3

    def test_mmrv_rt2x(self, results):
        assert abs(results["mmrv_scores"]["RT-2-X"] - 0.770) < 1e-3

    def test_mmrv_openvla(self, results):
        assert abs(results["mmrv_scores"]["OpenVLA"] - 0.552) < 1e-3

    def test_mmrv_spatialvla(self, results):
        assert abs(results["mmrv_scores"]["SpatialVLA"] - 0.606) < 1e-3

    def test_mmrv_diffusion(self, results):
        assert abs(results["mmrv_scores"]["DiffusionPolicy"] - 0.570) < 1e-3

    def test_mmrv_from_raw_data(self, evaluation_data, results):
        """Recompute MMRV directly from raw sim_results."""
        sim = evaluation_data["sim_results"]
        policies = evaluation_data["metadata"]["policies"]
        tasks_list = evaluation_data["metadata"]["tasks"]
        variants_list = evaluation_data["metadata"]["variants"]
        for policy in policies:
            max_per_task = []
            for task in tasks_list:
                vals = [sim[policy][task][v] for v in variants_list]
                max_per_task.append(max(vals))
            mmrv = sum(max_per_task) / len(max_per_task)
            assert abs(mmrv - results["mmrv_scores"][policy]) < 1e-6, (
                f"MMRV mismatch for {policy}: {mmrv:.6f} vs {results['mmrv_scores'][policy]:.6f}"
            )


class TestRealMeans:
    def test_real_mean_rt1(self, results):
        assert abs(results["real_mean_scores"]["RT-1"] - 0.604) < 1e-3

    def test_real_mean_rt2x(self, results):
        assert abs(results["real_mean_scores"]["RT-2-X"] - 0.750) < 1e-3

    def test_real_mean_octo_small(self, results):
        assert abs(results["real_mean_scores"]["Octo-Small"] - 0.290) < 1e-3

    def test_real_mean_diffusion(self, results):
        assert abs(results["real_mean_scores"]["DiffusionPolicy"] - 0.436) < 1e-3


class TestTaskCorrelations:
    """Per-task Pearson r between max-variant sim and real scores."""

    def test_all_task_correlations_high(self, results):
        for task, r in results["task_correlations"].items():
            assert r > 0.96, f"Task correlation for {task} too low: {r}"

    def test_pick_coke_can_correlation(self, results):
        assert abs(results["task_correlations"]["pick_coke_can"] - 0.9832) < 0.005

    def test_put_in_drawer_correlation(self, results):
        assert abs(results["task_correlations"]["put_in_drawer"] - 0.9671) < 0.005

    def test_task_correlations_recomputed(self, results, evaluation_data):
        """Recompute task correlations from raw data."""
        sim = evaluation_data["sim_results"]
        policies = evaluation_data["metadata"]["policies"]
        tasks_list = evaluation_data["metadata"]["tasks"]
        variants_list = evaluation_data["metadata"]["variants"]
        for task in tasks_list:
            max_sim = []
            real_vals = []
            for policy in policies:
                vals = [sim[policy][task][v] for v in variants_list]
                max_sim.append(max(vals))
                real_vals.append(evaluation_data["real_results"][policy][task])
            r, _ = stats.pearsonr(max_sim, real_vals)
            assert abs(r - results["task_correlations"][task]) < 1e-4, (
                f"Task correlation mismatch for {task}: {r:.6f} vs {results['task_correlations'][task]:.6f}"
            )


class TestFisherZTransform:
    def test_fisher_z_mean_valid(self, results):
        assert -1.0 < results["fisher_z_mean_r"] < 1.0

    def test_fisher_z_close_to_aggregate(self, results):
        """Fisher z-mean should be close to aggregate Pearson r."""
        assert abs(results["fisher_z_mean_r"] - results["aggregate_pearson_r"]) < 0.005

    def test_fisher_z_recomputed(self, results):
        """Recompute Fisher z-transform from task correlations."""
        z_vals = [np.arctanh(r) for r in results["task_correlations"].values()]
        mean_z = np.mean(z_vals)
        expected_r = float(np.tanh(mean_z))
        assert abs(expected_r - results["fisher_z_mean_r"]) < 1e-5, (
            f"Fisher z recomputed: {expected_r:.6f} vs {results['fisher_z_mean_r']:.6f}"
        )


class TestANOVA:
    """Variance decomposition of sim-real discrepancy."""

    def test_eta_squared_sum_less_than_one(self, results):
        eta = results["anova_eta_squared"]
        total = eta["policy"] + eta["task"] + eta["variant"]
        assert total < 1.0, f"Eta-squared sum exceeds 1: {total}"

    def test_variant_dominant_factor(self, results):
        """Variant should explain the most variance in sim-real discrepancy."""
        eta = results["anova_eta_squared"]
        assert eta["variant"] > 0.50, f"Variant eta-squared too low: {eta['variant']}"
        assert eta["variant"] > eta["policy"], "Variant should dominate policy effect"
        assert eta["variant"] > eta["task"], "Variant should dominate task effect"

    def test_task_effect_negligible(self, results):
        """Task effect should be very small."""
        assert results["anova_eta_squared"]["task"] < 0.01

    def test_policy_effect_moderate(self, results):
        """Policy effect should be moderate (around 10%)."""
        assert 0.05 < results["anova_eta_squared"]["policy"] < 0.20

    def test_f_stat_ordering(self, results):
        """F-stats should follow: variant >> policy >> task."""
        f = results["anova_f_stats"]
        assert f["variant"] > f["policy"] > f["task"], (
            f"Expected F(variant) > F(policy) > F(task), got {f}"
        )

    def test_variant_f_stat_significant(self, results):
        assert results["anova_f_stats"]["variant"] > 50.0, (
            f"Variant F-stat too low: {results['anova_f_stats']['variant']}"
        )

    def test_eta_squared_variant_value(self, results):
        assert abs(results["anova_eta_squared"]["variant"] - 0.554) < 0.02

    def test_f_stat_variant_value(self, results):
        assert abs(results["anova_f_stats"]["variant"] - 78.94) < 2.0

    def test_anova_recomputed(self, results, evaluation_data):
        """Recompute ANOVA from raw data to verify."""
        sim = evaluation_data["sim_results"]
        real = evaluation_data["real_results"]
        policies = evaluation_data["metadata"]["policies"]
        tasks_list = evaluation_data["metadata"]["tasks"]
        variants_list = evaluation_data["metadata"]["variants"]

        n_p, n_t, n_v = len(policies), len(tasks_list), len(variants_list)
        discrepancy = np.zeros((n_p, n_t, n_v))
        for pi, pol in enumerate(policies):
            for ti, tsk in enumerate(tasks_list):
                for vi, var in enumerate(variants_list):
                    discrepancy[pi, ti, vi] = sim[pol][tsk][var] - real[pol][tsk]

        grand_mean = discrepancy.mean()
        ss_total = np.sum((discrepancy - grand_mean) ** 2)

        policy_means = discrepancy.mean(axis=(1, 2))
        ss_policy = n_t * n_v * np.sum((policy_means - grand_mean) ** 2)

        task_means = discrepancy.mean(axis=(0, 2))
        ss_task = n_p * n_v * np.sum((task_means - grand_mean) ** 2)

        variant_means = discrepancy.mean(axis=(0, 1))
        ss_variant = n_p * n_t * np.sum((variant_means - grand_mean) ** 2)

        eta_policy = ss_policy / ss_total
        eta_task = ss_task / ss_total
        eta_variant = ss_variant / ss_total

        assert abs(eta_policy - results["anova_eta_squared"]["policy"]) < 1e-3
        assert abs(eta_task - results["anova_eta_squared"]["task"]) < 1e-3
        assert abs(eta_variant - results["anova_eta_squared"]["variant"]) < 1e-3


class TestDemingRegression:
    """Calibration regression with measurement noise in both variables."""

    def test_visual_match_standard_slope_near_one(self, results):
        """Standard variant should have slope close to 1 (good calibration)."""
        slope = results["deming_calibration"]["visual_match_standard"]["slope"]
        assert abs(slope - 1.0) < 0.05, f"Standard variant slope: {slope}"

    def test_alt_lighting_slope_above_one(self, results):
        """Alt lighting underestimates real performance -> slope > 1."""
        slope = results["deming_calibration"]["visual_match_alt_lighting"]["slope"]
        assert slope > 1.1, f"Alt lighting slope should be > 1.1: {slope}"

    def test_alt_lighting_slope_value(self, results):
        assert (
            abs(
                results["deming_calibration"]["visual_match_alt_lighting"]["slope"]
                - 1.243
            )
            < 0.03
        )

    def test_visual_match_standard_slope_value(self, results):
        assert (
            abs(
                results["deming_calibration"]["visual_match_standard"]["slope"] - 0.993
            )
            < 0.03
        )

    def test_all_slopes_positive(self, results):
        for v, cal in results["deming_calibration"].items():
            assert cal["slope"] > 0, f"Negative slope for {v}: {cal['slope']}"

    def test_deming_not_ols(self, results, evaluation_data):
        """Verify slopes differ from OLS — agent must account for noise in both variables."""
        sim_data = evaluation_data["sim_results"]
        real_data = evaluation_data["real_results"]
        policies = evaluation_data["metadata"]["policies"]
        tasks_list = evaluation_data["metadata"]["tasks"]
        variants_list = evaluation_data["metadata"]["variants"]

        for vi, variant in enumerate(variants_list):
            x = []
            y = []
            for pol in policies:
                for tsk in tasks_list:
                    x.append(sim_data[pol][tsk][variant])
                    y.append(real_data[pol][tsk])
            x = np.array(x)
            y = np.array(y)
            ols_slope, ols_intercept, _, _, _ = stats.linregress(x, y)
            deming_slope = results["deming_calibration"][variant]["slope"]
            if abs(ols_slope - deming_slope) > 0.001:
                return  # Found at least one variant where they differ
        pytest.fail(
            "Slopes identical to OLS — likely not accounting for measurement noise in both variables"
        )


class TestInfluenceDiagnostics:
    """Influence diagnostics for the aggregate sim to real model."""

    def test_leverage_sum(self, results, evaluation_data):
        """Sum of leverages should equal p (number of parameters = 2)."""
        h_sum = sum(d["leverage"] for d in results["influence_diagnostics"].values())
        assert abs(h_sum - 2.0) < 0.01, f"Leverage sum should be 2.0, got {h_sum}"

    def test_leverage_range(self, results, evaluation_data):
        n = len(evaluation_data["metadata"]["policies"])
        for p, d in results["influence_diagnostics"].items():
            assert 1.0 / n <= d["leverage"] + 1e-6, (
                f"Leverage for {p} below 1/n: {d['leverage']}"
            )
            assert d["leverage"] <= 1.0, (
                f"Leverage for {p} above 1: {d['leverage']}"
            )

    def test_diffusion_policy_max_cooks_d(self, results):
        """DiffusionPolicy should have the highest Cook's distance."""
        max_policy = max(
            results["influence_diagnostics"],
            key=lambda p: results["influence_diagnostics"][p]["cooks_d"],
        )
        assert max_policy == "DiffusionPolicy", (
            f"Expected DiffusionPolicy to have max Cook's D, got {max_policy}"
        )

    def test_diffusion_policy_cooks_d_value(self, results):
        d = results["influence_diagnostics"]["DiffusionPolicy"]["cooks_d"]
        assert abs(d - 0.394) < 0.05, f"DiffusionPolicy Cook's D: {d}"

    def test_diffusion_policy_dffits_large(self, results):
        """DiffusionPolicy should be the only policy with |DFFITS| > 1.0."""
        large_dffits = [
            p
            for p, d in results["influence_diagnostics"].items()
            if abs(d["dffits"]) > 1.0
        ]
        assert "DiffusionPolicy" in large_dffits, (
            "DiffusionPolicy should have |DFFITS| > 1.0"
        )

    def test_diffusion_policy_dffits_value(self, results):
        d = results["influence_diagnostics"]["DiffusionPolicy"]["dffits"]
        assert abs(d - (-2.809)) < 0.15, f"DiffusionPolicy DFFITS: {d}"

    def test_octo_small_highest_leverage(self, results):
        """Octo-Small (most extreme MMRV) should have highest leverage."""
        max_lev_policy = max(
            results["influence_diagnostics"],
            key=lambda p: results["influence_diagnostics"][p]["leverage"],
        )
        assert max_lev_policy == "Octo-Small", (
            f"Expected Octo-Small to have max leverage, got {max_lev_policy}"
        )

    def test_cooks_d_all_nonnegative(self, results):
        for p, d in results["influence_diagnostics"].items():
            assert d["cooks_d"] >= -1e-10, f"Negative Cook's D for {p}: {d['cooks_d']}"

    def test_influence_consistency(self, results):
        """Recompute from MMRV and real scores."""
        policies = list(results["mmrv_scores"].keys())
        n = len(policies)
        x_vals = np.array([results["mmrv_scores"][p] for p in policies])
        y_vals = np.array([results["real_mean_scores"][p] for p in policies])
        X = np.column_stack([np.ones(n), x_vals])
        H = X @ np.linalg.inv(X.T @ X) @ X.T
        h = np.diag(H)
        beta = np.linalg.inv(X.T @ X) @ X.T @ y_vals
        y_hat = X @ beta
        e = y_vals - y_hat
        p_params = 2
        MSE = np.sum(e**2) / (n - p_params)
        cooks_d = (e**2 * h) / (p_params * MSE * (1 - h) ** 2)
        for i, pol in enumerate(policies):
            reported = results["influence_diagnostics"][pol]["cooks_d"]
            assert abs(cooks_d[i] - reported) < 0.02, (
                f"Cook's D mismatch for {pol}: computed {cooks_d[i]:.6f} vs reported {reported:.6f}"
            )


class TestPermutationTest:
    def test_p_value_significant(self, results):
        """Correlation should be highly significant."""
        assert results["permutation_p_value"] < 0.001, (
            f"p-value too high: {results['permutation_p_value']}"
        )

    def test_p_value_positive(self, results):
        assert results["permutation_p_value"] > 0, "p-value should be positive"

    def test_p_value_very_small(self, results):
        """With 50000 permutations, p-value should be on order of 1e-4."""
        assert results["permutation_p_value"] < 0.0005


class TestConformalPrediction:
    def test_intervals_contain_predicted(self, results):
        """Predicted value should be within the interval."""
        for p, ci in results["conformal_intervals"].items():
            assert ci["lower"] <= ci["predicted"] <= ci["upper"], (
                f"Predicted value outside interval for {p}"
            )

    def test_interval_ordering(self, results):
        for p, ci in results["conformal_intervals"].items():
            assert ci["lower"] < ci["upper"], (
                f"Lower >= upper for {p}: [{ci['lower']}, {ci['upper']}]"
            )

    def test_coverage_reasonable(self, results):
        """At least 6/8 actual values should fall within 90% conformal intervals."""
        covered = 0
        for p, ci in results["conformal_intervals"].items():
            real_val = results["real_mean_scores"][p]
            if ci["lower"] <= real_val <= ci["upper"]:
                covered += 1
        assert covered >= 6, (
            f"Only {covered}/8 actual values in 90% intervals (expected >= 6)"
        )

    def test_interval_widths_reasonable(self, results):
        """Interval widths should be reasonable (not trivially wide or narrow)."""
        for p, ci in results["conformal_intervals"].items():
            width = ci["upper"] - ci["lower"]
            assert 0.05 < width < 0.30, (
                f"Interval width for {p} seems unreasonable: {width}"
            )

    def test_predicted_values_match_ols(self, results):
        """Conformal predicted values should match OLS fitted values."""
        policies = list(results["mmrv_scores"].keys())
        n = len(policies)
        x_vals = np.array([results["mmrv_scores"][p] for p in policies])
        y_vals = np.array([results["real_mean_scores"][p] for p in policies])
        X = np.column_stack([np.ones(n), x_vals])
        beta = np.linalg.inv(X.T @ X) @ X.T @ y_vals
        y_hat = X @ beta
        for i, pol in enumerate(policies):
            pred = results["conformal_intervals"][pol]["predicted"]
            assert abs(pred - y_hat[i]) < 0.01, (
                f"Predicted value for {pol} doesn't match OLS: {pred} vs {y_hat[i]}"
            )


class TestAggregatePearson:
    def test_aggregate_r_range(self, results):
        assert -1.0 <= results["aggregate_pearson_r"] <= 1.0

    def test_aggregate_r_value(self, results):
        assert abs(results["aggregate_pearson_r"] - 0.975) < 0.015

    def test_aggregate_r_recomputed(self, results):
        """Recompute Pearson r from reported MMRV and real scores."""
        policies = list(results["mmrv_scores"].keys())
        mmrv_vals = [results["mmrv_scores"][p] for p in policies]
        real_vals = [results["real_mean_scores"][p] for p in policies]
        r, _ = stats.pearsonr(mmrv_vals, real_vals)
        assert abs(r - results["aggregate_pearson_r"]) < 1e-3
