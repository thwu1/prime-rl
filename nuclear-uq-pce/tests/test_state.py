
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, "/app")


def load_results():
    with open("/app/results.json", "r") as f:
        return json.load(f)


def vectorized_mc_reference(n_samples=200000, seed=42):
    """Compute Monte Carlo reference statistics using vectorized model evaluation."""
    rng = np.random.RandomState(seed)

    x0 = rng.uniform(0.9, 1.1, n_samples)
    x1 = rng.normal(0.0, 5.0, n_samples)
    x2 = rng.uniform(0.95, 1.05, n_samples)
    x3 = rng.normal(1.0, 0.03, n_samples)

    T_in = 565.0 + x1
    q = 0.6e6 * x0
    P = 15.5 * x2
    G = 3800.0 * x3
    D_h, L = 0.0118, 3.66
    cp, k_c, mu = 5500.0, 0.56, 8.7e-5
    Pr = cp * mu / k_c

    Re = G * D_h / mu
    h = 0.023 * Re**0.8 * Pr**0.4 * k_c / D_h

    dT = 4.0 * q * L / (G * D_h * cp)
    T_out = T_in + dT
    T_clad = T_out + q / h

    subcool = 620.0 - T_out
    CHF = (
        3.5e6
        * np.sqrt(G / 3800.0)
        * (1.0 + 0.002 * subcool)
        * (1.0 - 0.012 * (P - 15.5))
    )
    dnbr = CHF / q

    return {
        "peak_clad_temp": {"mean": float(np.mean(T_clad)), "variance": float(np.var(T_clad))},
        "dnbr": {"mean": float(np.mean(dnbr)), "variance": float(np.var(dnbr))},
    }


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------
class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found at /app/results.json"

    def test_has_statistics(self):
        results = load_results()
        assert "statistics" in results, "Missing 'statistics' key in results"

    def test_has_sobol_indices(self):
        results = load_results()
        assert "sobol_indices" in results, "Missing 'sobol_indices' key in results"

    def test_output_names_present(self):
        results = load_results()
        for name in ["peak_clad_temp", "dnbr"]:
            assert name in results["statistics"], f"Missing '{name}' in statistics"
            assert name in results["sobol_indices"], f"Missing '{name}' in sobol_indices"

    def test_statistics_fields(self):
        results = load_results()
        for name in ["peak_clad_temp", "dnbr"]:
            stats = results["statistics"][name]
            for field in ["mean", "variance", "std"]:
                assert field in stats, f"Missing '{field}' in {name} statistics"
                assert isinstance(stats[field], (int, float)), f"'{field}' in {name} must be numeric"

    def test_sobol_fields(self):
        results = load_results()
        input_names = [
            "power_level",
            "inlet_temp_perturbation",
            "pressure_factor",
            "flow_rate_factor",
        ]
        for out_name in ["peak_clad_temp", "dnbr"]:
            sobol = results["sobol_indices"][out_name]
            assert "first_order" in sobol, f"Missing 'first_order' in {out_name} Sobol"
            assert "total_order" in sobol, f"Missing 'total_order' in {out_name} Sobol"
            for inp_name in input_names:
                assert inp_name in sobol["first_order"], (
                    f"Missing '{inp_name}' in {out_name} first-order Sobol"
                )
                assert inp_name in sobol["total_order"], (
                    f"Missing '{inp_name}' in {out_name} total-order Sobol"
                )


# ---------------------------------------------------------------------------
# Statistics accuracy tests
# ---------------------------------------------------------------------------
class TestStatisticsAccuracy:
    @pytest.fixture(scope="class")
    def mc_ref(self):
        return vectorized_mc_reference()

    def test_peak_clad_temp_mean(self, mc_ref):
        results = load_results()
        pce = results["statistics"]["peak_clad_temp"]["mean"]
        mc = mc_ref["peak_clad_temp"]["mean"]
        rel_err = abs(pce - mc) / abs(mc)
        assert rel_err < 0.005, (
            f"PCT mean relative error {rel_err:.6f} exceeds 0.5%: PCE={pce:.4f}, MC={mc:.4f}"
        )

    def test_peak_clad_temp_variance(self, mc_ref):
        results = load_results()
        pce = results["statistics"]["peak_clad_temp"]["variance"]
        mc = mc_ref["peak_clad_temp"]["variance"]
        rel_err = abs(pce - mc) / abs(mc)
        assert rel_err < 0.05, (
            f"PCT variance relative error {rel_err:.6f} exceeds 5%: PCE={pce:.4f}, MC={mc:.4f}"
        )

    def test_peak_clad_temp_std_consistency(self):
        results = load_results()
        stats = results["statistics"]["peak_clad_temp"]
        expected_std = np.sqrt(stats["variance"])
        rel_err = abs(stats["std"] - expected_std) / abs(expected_std)
        assert rel_err < 1e-6, (
            f"PCT std != sqrt(variance): std={stats['std']}, sqrt(var)={expected_std}"
        )

    def test_dnbr_mean(self, mc_ref):
        results = load_results()
        pce = results["statistics"]["dnbr"]["mean"]
        mc = mc_ref["dnbr"]["mean"]
        rel_err = abs(pce - mc) / abs(mc)
        assert rel_err < 0.005, (
            f"DNBR mean relative error {rel_err:.6f} exceeds 0.5%: PCE={pce:.4f}, MC={mc:.4f}"
        )

    def test_dnbr_variance(self, mc_ref):
        results = load_results()
        pce = results["statistics"]["dnbr"]["variance"]
        mc = mc_ref["dnbr"]["variance"]
        rel_err = abs(pce - mc) / abs(mc)
        assert rel_err < 0.05, (
            f"DNBR variance relative error {rel_err:.6f} exceeds 5%: PCE={pce:.4f}, MC={mc:.4f}"
        )

    def test_dnbr_std_consistency(self):
        results = load_results()
        stats = results["statistics"]["dnbr"]
        expected_std = np.sqrt(stats["variance"])
        rel_err = abs(stats["std"] - expected_std) / abs(expected_std)
        assert rel_err < 1e-6, (
            f"DNBR std != sqrt(variance): std={stats['std']}, sqrt(var)={expected_std}"
        )


# ---------------------------------------------------------------------------
# Sobol index property tests
# ---------------------------------------------------------------------------
class TestSobolProperties:
    def test_first_order_nonnegative(self):
        results = load_results()
        for out_name in ["peak_clad_temp", "dnbr"]:
            for inp_name, val in results["sobol_indices"][out_name]["first_order"].items():
                assert val >= -0.01, (
                    f"First-order Sobol {inp_name}->{out_name} is negative: {val}"
                )

    def test_total_order_nonnegative(self):
        results = load_results()
        for out_name in ["peak_clad_temp", "dnbr"]:
            for inp_name, val in results["sobol_indices"][out_name]["total_order"].items():
                assert val >= -0.01, (
                    f"Total-order Sobol {inp_name}->{out_name} is negative: {val}"
                )

    def test_first_order_sum_leq_one(self):
        results = load_results()
        for out_name in ["peak_clad_temp", "dnbr"]:
            s1_sum = sum(results["sobol_indices"][out_name]["first_order"].values())
            assert s1_sum <= 1.05, (
                f"Sum of first-order Sobol indices for {out_name} exceeds 1: {s1_sum:.4f}"
            )

    def test_total_order_sum_geq_one(self):
        results = load_results()
        for out_name in ["peak_clad_temp", "dnbr"]:
            st_sum = sum(results["sobol_indices"][out_name]["total_order"].values())
            assert st_sum >= 0.90, (
                f"Sum of total-order Sobol indices for {out_name} below threshold: {st_sum:.4f}"
            )

    def test_total_geq_first_order(self):
        results = load_results()
        for out_name in ["peak_clad_temp", "dnbr"]:
            sobol = results["sobol_indices"][out_name]
            for inp_name in sobol["first_order"]:
                s1 = sobol["first_order"][inp_name]
                st = sobol["total_order"][inp_name]
                assert st >= s1 - 0.02, (
                    f"Total < first for {inp_name}->{out_name}: ST={st:.4f}, S1={s1:.4f}"
                )


# ---------------------------------------------------------------------------
# Physics-motivated sensitivity ranking tests
# ---------------------------------------------------------------------------
class TestSobolDominantInputs:
    def test_pct_inlet_temp_dominant(self):
        """Inlet temperature perturbation (sigma=5K, direct additive) should dominate PCT."""
        results = load_results()
        s1 = results["sobol_indices"]["peak_clad_temp"]["first_order"]["inlet_temp_perturbation"]
        assert s1 > 0.3, f"Expected inlet_temp to dominate PCT, got S1={s1:.4f}"

    def test_pct_power_significant(self):
        """Power level affects heat flux and thus PCT."""
        results = load_results()
        s1 = results["sobol_indices"]["peak_clad_temp"]["first_order"]["power_level"]
        assert s1 > 0.05, f"Expected power_level significant for PCT, got S1={s1:.4f}"

    def test_pct_pressure_negligible(self):
        """Pressure factor does not appear in the temperature equations."""
        results = load_results()
        s1 = results["sobol_indices"]["peak_clad_temp"]["first_order"]["pressure_factor"]
        assert s1 < 0.02, f"Pressure Sobol unexpectedly high for PCT: {s1:.6f}"

    def test_dnbr_power_dominant(self):
        """Power level is in the DNBR denominator and should dominate."""
        results = load_results()
        s1 = results["sobol_indices"]["dnbr"]["first_order"]["power_level"]
        assert s1 > 0.3, f"Expected power_level to dominate DNBR, got S1={s1:.4f}"

    def test_pct_mean_near_nominal(self):
        """PCE mean should be within 5% of the model evaluated at nominal inputs."""
        from model import evaluate

        y_nom = evaluate([1.0, 0.0, 1.0, 1.0])
        results = load_results()
        pct_mean = results["statistics"]["peak_clad_temp"]["mean"]
        rel_err = abs(pct_mean - y_nom[0]) / abs(y_nom[0])
        assert rel_err < 0.05, (
            f"PCT mean too far from nominal: mean={pct_mean:.2f}, nominal={y_nom[0]:.2f}"
        )

    def test_dnbr_mean_near_nominal(self):
        """DNBR mean should be within 5% of the model evaluated at nominal inputs."""
        from model import evaluate

        y_nom = evaluate([1.0, 0.0, 1.0, 1.0])
        results = load_results()
        dnbr_mean = results["statistics"]["dnbr"]["mean"]
        rel_err = abs(dnbr_mean - y_nom[1]) / abs(y_nom[1])
        assert rel_err < 0.05, (
            f"DNBR mean too far from nominal: mean={dnbr_mean:.4f}, nominal={y_nom[1]:.4f}"
        )
