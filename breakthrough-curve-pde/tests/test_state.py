"""
Tests for fixed-bed adsorption breakthrough curve analysis pipeline.
Verifies /app/results.json against known values and physical constraints.
"""

import pytest
import json
import os
import numpy as np


@pytest.fixture(scope="session")
def results():
    """Load results.json produced by analyze.py."""
    path = "/app/results.json"
    assert os.path.exists(path), (
        "results.json not found. analyze.py must produce /app/results.json"
    )
    with open(path) as f:
        data = json.load(f)
    return data


# Golden Yoon-Nelson parameters (data was generated from these exact values)
YN_GOLDEN = {
    "A": {"k_YN": 0.029, "tau": 280.82},
    "B": {"k_YN": 0.021, "tau": 382.38},
    "C": {"k_YN": 0.020, "tau": 536.84},
    "D": {"k_YN": 0.031, "tau": 168.09},
    "E": {"k_YN": 0.026, "tau": 103.44},
}

CURVES = list("ABCDE")
VAL_CURVES = list("BCDE")
BED_HEIGHTS = {"A": 4.5, "B": 4.5, "C": 4.5, "D": 3.0, "E": 4.5}

# Approximate expected breakthrough/exhaustion times (from data interpolation)
TB_EXPECTED = {"A": 179, "B": 242, "C": 389, "D": 73, "E": 0}
TE_EXPECTED = {"A": 382, "B": 523, "C": 684, "D": 263, "E": 217}


# ==================================================================
# Structure tests
# ==================================================================
class TestResultStructure:
    def test_top_level_sections(self, results):
        for section in ["yoon_nelson", "thomas", "adams_bohart", "capacity",
                        "mtz", "bdst", "pde_model", "sensitivity"]:
            assert section in results, f"Missing top-level section: {section}"

    @pytest.mark.parametrize("section",
                             ["yoon_nelson", "thomas", "adams_bohart", "mtz",
                              "capacity"])
    def test_all_curves_present(self, results, section):
        for curve in CURVES:
            assert curve in results[section], (
                f"Missing curve {curve} in {section}"
            )

    def test_yn_ci_keys(self, results):
        for curve in CURVES:
            yn = results["yoon_nelson"][curve]
            assert "k_YN_ci95" in yn, f"Missing k_YN_ci95 for {curve}"
            assert "tau_ci95" in yn, f"Missing tau_ci95 for {curve}"
            assert len(yn["k_YN_ci95"]) == 2, "k_YN_ci95 must have 2 elements"
            assert len(yn["tau_ci95"]) == 2, "tau_ci95 must have 2 elements"

    def test_pde_calibration_keys(self, results):
        cal = results["pde_model"]["calibration"]
        for key in ["k_LDF", "q_max_mg_g", "R2", "RMSE"]:
            assert key in cal, f"Missing calibration key: {key}"

    def test_pde_validation_curves(self, results):
        val = results["pde_model"]["validation"]
        for curve in VAL_CURVES:
            assert curve in val, f"Missing validation curve {curve}"
            for key in ["R2", "RMSE"]:
                assert key in val[curve], (
                    f"Missing key {key} in validation[{curve}]"
                )

    def test_bdst_keys(self, results):
        for key in ["slope", "intercept", "N_0", "k_a", "Z_0"]:
            assert key in results["bdst"], f"Missing BDST key: {key}"

    def test_sensitivity_keys(self, results):
        sens = results["sensitivity"]
        for key in ["k_LDF_plus20", "k_LDF_minus20",
                     "q_max_plus20", "q_max_minus20"]:
            assert key in sens, f"Missing sensitivity key: {key}"
            assert "R2" in sens[key], f"Missing R2 in sensitivity[{key}]"
            assert "RMSE" in sens[key], f"Missing RMSE in sensitivity[{key}]"

    def test_capacity_keys(self, results):
        for curve in CURVES:
            assert "q_exp_mg_g" in results["capacity"][curve], (
                f"Missing q_exp_mg_g for {curve}"
            )


# ==================================================================
# Yoon-Nelson model tests
# ==================================================================
class TestYoonNelson:
    @pytest.mark.parametrize("curve", CURVES)
    def test_k_YN_accuracy(self, results, curve):
        k = results["yoon_nelson"][curve]["k_YN"]
        k_exp = YN_GOLDEN[curve]["k_YN"]
        assert abs(k - k_exp) / k_exp < 0.05, (
            f"k_YN for {curve}: got {k:.6f}, expected ~{k_exp}"
        )

    @pytest.mark.parametrize("curve", CURVES)
    def test_tau_accuracy(self, results, curve):
        tau = results["yoon_nelson"][curve]["tau"]
        tau_exp = YN_GOLDEN[curve]["tau"]
        assert abs(tau - tau_exp) / tau_exp < 0.02, (
            f"tau for {curve}: got {tau:.4f}, expected ~{tau_exp}"
        )

    @pytest.mark.parametrize("curve", CURVES)
    def test_R2_near_unity(self, results, curve):
        R2 = results["yoon_nelson"][curve]["R2"]
        assert R2 > 0.999, f"YN R2 for {curve}: {R2:.6f} (expect > 0.999)"

    @pytest.mark.parametrize("curve", CURVES)
    def test_ci_brackets_k_YN(self, results, curve):
        yn = results["yoon_nelson"][curve]
        lo, hi = yn["k_YN_ci95"]
        assert lo < yn["k_YN"] < hi, (
            f"CI [{lo}, {hi}] does not bracket k_YN={yn['k_YN']}"
        )

    @pytest.mark.parametrize("curve", CURVES)
    def test_ci_brackets_tau(self, results, curve):
        yn = results["yoon_nelson"][curve]
        lo, hi = yn["tau_ci95"]
        assert lo < yn["tau"] < hi, (
            f"CI [{lo}, {hi}] does not bracket tau={yn['tau']}"
        )

    @pytest.mark.parametrize("curve", CURVES)
    def test_ci_width_k_YN(self, results, curve):
        yn = results["yoon_nelson"][curve]
        width = yn["k_YN_ci95"][1] - yn["k_YN_ci95"][0]
        assert width < 0.5 * yn["k_YN"], (
            f"k_YN CI too wide: {width:.6f} vs value {yn['k_YN']:.6f}"
        )

    @pytest.mark.parametrize("curve", CURVES)
    def test_ci_width_tau(self, results, curve):
        yn = results["yoon_nelson"][curve]
        width = yn["tau_ci95"][1] - yn["tau_ci95"][0]
        assert width < 0.05 * yn["tau"], (
            f"tau CI too wide: {width:.4f} vs value {yn['tau']:.4f}"
        )


# ==================================================================
# Thomas model tests
# ==================================================================
class TestThomas:
    @pytest.mark.parametrize("curve", CURVES)
    def test_R2_high(self, results, curve):
        R2 = results["thomas"][curve]["R2"]
        assert R2 > 0.999, f"Thomas R2 for {curve}: {R2:.6f}"

    @pytest.mark.parametrize("curve", CURVES)
    def test_k_Th_positive(self, results, curve):
        assert results["thomas"][curve]["k_Th"] > 0

    @pytest.mark.parametrize("curve", CURVES)
    def test_q_0_positive(self, results, curve):
        assert results["thomas"][curve]["q_0"] > 0

    @pytest.mark.parametrize("curve", CURVES)
    def test_k_Th_reasonable_range(self, results, curve):
        k = results["thomas"][curve]["k_Th"]
        assert 0.01 < k < 10.0, f"k_Th for {curve} out of range: {k}"

    @pytest.mark.parametrize("curve", CURVES)
    def test_q_0_reasonable_range(self, results, curve):
        q = results["thomas"][curve]["q_0"]
        assert 0.01 < q < 50.0, f"q_0 for {curve} out of range: {q}"


# ==================================================================
# Adams-Bohart model tests
# ==================================================================
class TestAdamsBohart:
    @pytest.mark.parametrize("curve", CURVES)
    def test_R2_good(self, results, curve):
        R2 = results["adams_bohart"][curve]["R2"]
        assert R2 > 0.90, f"Adams-Bohart R2 for {curve}: {R2:.4f}"

    @pytest.mark.parametrize("curve", CURVES)
    def test_k_AB_positive(self, results, curve):
        assert results["adams_bohart"][curve]["k_AB"] > 0

    @pytest.mark.parametrize("curve", CURVES)
    def test_N_0_positive(self, results, curve):
        assert results["adams_bohart"][curve]["N_0"] > 0


# ==================================================================
# Capacity tests
# ==================================================================
class TestCapacity:
    @pytest.mark.parametrize("curve", CURVES)
    def test_q_exp_positive(self, results, curve):
        q = results["capacity"][curve]["q_exp_mg_g"]
        assert q > 0, f"q_exp for {curve} must be positive: {q}"

    @pytest.mark.parametrize("curve", CURVES)
    def test_q_exp_range(self, results, curve):
        q = results["capacity"][curve]["q_exp_mg_g"]
        assert 0.05 < q < 5.0, f"q_exp for {curve} out of range: {q}"

    def test_higher_C0_higher_capacity(self, results):
        """Curve A (C0=100, Q=1) should have higher capacity than
        Curve C (C0=50, Q=1) at same bed height and flow rate."""
        q_A = results["capacity"]["A"]["q_exp_mg_g"]
        q_C = results["capacity"]["C"]["q_exp_mg_g"]
        assert q_A > q_C, (
            f"Expected q_A ({q_A:.4f}) > q_C ({q_C:.4f})"
        )

    def test_capacity_consistent_with_yn_tau(self, results):
        """Capacity should be proportional to C0*Q*tau/m for symmetric curves.
        Check curve A is within 50% of the YN-based estimate."""
        q_A = results["capacity"]["A"]["q_exp_mg_g"]
        tau_A = results["yoon_nelson"]["A"]["tau"]
        # Approximate: q ~ C0*Q*tau/m where m ~ 48.6g for curve A
        q_yn_est = 100 * 0.001 * tau_A / 48.6
        assert abs(q_A - q_yn_est) / q_yn_est < 0.5, (
            f"q_exp_A ({q_A:.4f}) not consistent with YN estimate ({q_yn_est:.4f})"
        )


# ==================================================================
# MTZ analysis tests
# ==================================================================
class TestMTZ:
    @pytest.mark.parametrize("curve", ["A", "B", "C", "D"])
    def test_t_b_accuracy(self, results, curve):
        t_b = results["mtz"][curve]["t_b"]
        t_exp = TB_EXPECTED[curve]
        assert abs(t_b - t_exp) / max(t_exp, 1) < 0.08, (
            f"t_b for {curve}: got {t_b:.1f}, expected ~{t_exp}"
        )

    def test_t_b_E_near_zero(self, results):
        t_b = results["mtz"]["E"]["t_b"]
        assert t_b < 5, f"t_b for E should be ~0, got {t_b}"

    @pytest.mark.parametrize("curve", CURVES)
    def test_t_e_accuracy(self, results, curve):
        t_e = results["mtz"][curve]["t_e"]
        t_exp = TE_EXPECTED[curve]
        assert abs(t_e - t_exp) / t_exp < 0.08, (
            f"t_e for {curve}: got {t_e:.1f}, expected ~{t_exp}"
        )

    @pytest.mark.parametrize("curve", CURVES)
    def test_H_MTZ_physical(self, results, curve):
        H = results["mtz"][curve]["H_MTZ_cm"]
        Z = BED_HEIGHTS[curve]
        assert 0 < H <= Z * 1.01, (
            f"H_MTZ for {curve}: {H:.3f} (bed height = {Z})"
        )

    @pytest.mark.parametrize("curve", CURVES)
    def test_f_b_range(self, results, curve):
        f = results["mtz"][curve]["f_b"]
        assert 0 <= f <= 1.0, f"f_b for {curve}: {f}"

    @pytest.mark.parametrize("curve", ["A", "B", "C", "D"])
    def test_f_b_nonzero(self, results, curve):
        f = results["mtz"][curve]["f_b"]
        assert f > 0.25, f"f_b for {curve} too low: {f}"

    def test_H_MTZ_A_value(self, results):
        H = results["mtz"]["A"]["H_MTZ_cm"]
        assert 1.8 < H < 3.0, f"H_MTZ for A expected ~2.4, got {H:.3f}"

    def test_f_b_A_value(self, results):
        f = results["mtz"]["A"]["f_b"]
        assert 0.50 < f < 0.80, f"f_b for A expected ~0.63, got {f:.4f}"


# ==================================================================
# BDST analysis tests
# ==================================================================
class TestBDST:
    def test_slope_positive(self, results):
        assert results["bdst"]["slope"] > 0

    def test_intercept_negative(self, results):
        assert results["bdst"]["intercept"] < 0

    def test_N_0_positive(self, results):
        assert results["bdst"]["N_0"] > 0

    def test_k_a_positive(self, results):
        assert results["bdst"]["k_a"] > 0

    def test_Z_0_range(self, results):
        Z0 = results["bdst"]["Z_0"]
        assert 1.0 < Z0 < 2.8, f"Z_0 expected ~2.0, got {Z0:.3f}"

    def test_slope_range(self, results):
        slope = results["bdst"]["slope"]
        assert 40 < slope < 120, f"BDST slope expected ~70, got {slope:.2f}"

    def test_N_0_range(self, results):
        N0 = results["bdst"]["N_0"]
        assert 100 < N0 < 1500, f"BDST N_0 expected ~445, got {N0:.1f}"

    def test_k_a_range(self, results):
        k_a = results["bdst"]["k_a"]
        assert 5e-5 < k_a < 1e-3, f"BDST k_a expected ~2e-4, got {k_a:.2e}"


# ==================================================================
# PDE model calibration tests
# ==================================================================
class TestPDECalibration:
    def test_R2_high(self, results):
        R2 = results["pde_model"]["calibration"]["R2"]
        assert R2 > 0.90, f"PDE calibration R2: {R2:.4f}"

    def test_RMSE_low(self, results):
        rmse = results["pde_model"]["calibration"]["RMSE"]
        assert rmse < 0.10, f"PDE calibration RMSE: {rmse:.6f}"

    def test_k_LDF_range(self, results):
        k = results["pde_model"]["calibration"]["k_LDF"]
        assert 1e-5 < k < 1e-1, f"k_LDF out of range: {k:.2e}"

    def test_q_max_range(self, results):
        q = results["pde_model"]["calibration"]["q_max_mg_g"]
        assert 0.1 < q < 30, f"q_max out of range: {q:.4f}"


# ==================================================================
# PDE model validation tests
# ==================================================================
class TestPDEValidation:
    @pytest.mark.parametrize("curve", VAL_CURVES)
    def test_R2_acceptable(self, results, curve):
        R2 = results["pde_model"]["validation"][curve]["R2"]
        assert R2 > 0.70, (
            f"PDE validation R2 for {curve}: {R2:.4f} (need > 0.70)"
        )

    @pytest.mark.parametrize("curve", VAL_CURVES)
    def test_RMSE_bounded(self, results, curve):
        rmse = results["pde_model"]["validation"][curve]["RMSE"]
        assert rmse < 0.20, (
            f"PDE validation RMSE for {curve}: {rmse:.4f} (need < 0.20)"
        )

    def test_B_C_better_than_E(self, results):
        """Curves B and C (same geometry) should predict better than E
        (different flow rate)."""
        r2_b = results["pde_model"]["validation"]["B"]["R2"]
        r2_c = results["pde_model"]["validation"]["C"]["R2"]
        r2_e = results["pde_model"]["validation"]["E"]["R2"]
        avg_bc = (r2_b + r2_c) / 2
        assert avg_bc >= r2_e - 0.05, (
            f"Expected B,C validation ({avg_bc:.3f}) >= E ({r2_e:.3f})"
        )


# ==================================================================
# Sensitivity analysis tests
# ==================================================================
class TestSensitivity:
    def test_all_perturbations_valid(self, results):
        for key in ["k_LDF_plus20", "k_LDF_minus20",
                     "q_max_plus20", "q_max_minus20"]:
            r2 = results["sensitivity"][key]["R2"]
            rmse = results["sensitivity"][key]["RMSE"]
            assert isinstance(r2, float), f"R2 not float in {key}"
            assert isinstance(rmse, float), f"RMSE not float in {key}"
            assert rmse >= 0, f"Negative RMSE in {key}"

    def test_perturbation_degrades_fit(self, results):
        """At least 3 of 4 perturbations should have equal or higher RMSE
        than the optimal calibration (within small tolerance)."""
        cal_rmse = results["pde_model"]["calibration"]["RMSE"]
        worse_count = 0
        for key in ["k_LDF_plus20", "k_LDF_minus20",
                     "q_max_plus20", "q_max_minus20"]:
            if results["sensitivity"][key]["RMSE"] >= cal_rmse - 0.005:
                worse_count += 1
        assert worse_count >= 3, (
            f"Only {worse_count}/4 perturbations have RMSE >= calibration "
            f"RMSE ({cal_rmse:.6f}). Calibration may not be at optimum."
        )

    def test_sensitivity_rmse_not_zero(self, results):
        for key in ["k_LDF_plus20", "k_LDF_minus20",
                     "q_max_plus20", "q_max_minus20"]:
            assert results["sensitivity"][key]["RMSE"] > 0, (
                f"RMSE should not be zero for perturbed {key}"
            )

    def test_sensitivity_r2_bounded(self, results):
        for key in ["k_LDF_plus20", "k_LDF_minus20",
                     "q_max_plus20", "q_max_minus20"]:
            r2 = results["sensitivity"][key]["R2"]
            assert 0 <= r2 <= 1.0, (
                f"R2 out of [0,1] for {key}: {r2}"
            )

    def test_mean_perturbed_rmse_higher(self, results):
        """Mean RMSE across perturbations should exceed calibration RMSE."""
        cal_rmse = results["pde_model"]["calibration"]["RMSE"]
        mean_pert = np.mean([
            results["sensitivity"][k]["RMSE"]
            for k in ["k_LDF_plus20", "k_LDF_minus20",
                       "q_max_plus20", "q_max_minus20"]
        ])
        assert mean_pert >= cal_rmse * 0.95, (
            f"Mean perturbed RMSE ({mean_pert:.6f}) should be >= "
            f"0.95 * calibration RMSE ({cal_rmse:.6f})"
        )


# ==================================================================
# Cross-consistency checks
# ==================================================================
class TestCrossConsistency:
    def test_yn_thomas_equivalent_R2(self, results):
        """Thomas and YN are equivalent functional forms; R2 should match."""
        for curve in CURVES:
            r2_yn = results["yoon_nelson"][curve]["R2"]
            r2_th = results["thomas"][curve]["R2"]
            assert abs(r2_yn - r2_th) < 0.01, (
                f"Curve {curve}: YN R2={r2_yn:.6f} vs Thomas R2={r2_th:.6f}"
            )

    def test_mtz_ordering(self, results):
        """Curves with higher C0 or shorter bed should break through earlier."""
        t_b_A = results["mtz"]["A"]["t_b"]  # C0=100, Z=4.5
        t_b_D = results["mtz"]["D"]["t_b"]  # C0=100, Z=3.0
        assert t_b_A > t_b_D, (
            f"Curve A (Z=4.5) should have t_b > Curve D (Z=3.0)"
        )

    def test_lower_C0_later_breakthrough(self, results):
        """Lower inlet concentration should give later breakthrough."""
        t_b_A = results["mtz"]["A"]["t_b"]  # C0=100
        t_b_C = results["mtz"]["C"]["t_b"]  # C0=50
        assert t_b_C > t_b_A, (
            f"Curve C (C0=50) should break through later than A (C0=100)"
        )

    def test_capacity_ordering_by_bed_height(self, results):
        """Same C0 and Q but taller bed (A, Z=4.5) should adsorb more
        total mass per gram than shorter bed (D, Z=3.0) due to more
        contact time, reflected in higher q_exp."""
        q_A = results["capacity"]["A"]["q_exp_mg_g"]
        q_D = results["capacity"]["D"]["q_exp_mg_g"]
        assert q_A > q_D, (
            f"Expected q_A ({q_A:.4f}) > q_D ({q_D:.4f}) for taller bed"
        )
