
import json
import csv
import math
import os
import pytest
import numpy as np


OUTPUT_DIR = "/app/output"
DATA_DIR = "/app/data"


def load_json(path):
    with open(path) as f:
        return json.load(f)


# ============================================================
# Helpers
# ============================================================

def swift(eps_p, K, eps_0, n):
    return K * (eps_0 + eps_p) ** n


def voce(eps_p, sigma_sat, sigma_y, theta):
    return sigma_sat - (sigma_sat - sigma_y) * math.exp(-theta * eps_p)


def hockett_sherby(eps_p, sigma_sat, sigma_i, m, n):
    return sigma_sat - (sigma_sat - sigma_i) * math.exp(-m * eps_p ** n)


def rmse(predicted, actual):
    n = len(actual)
    return math.sqrt(sum((p - a) ** 2 for p, a in zip(predicted, actual)) / n)


def eval_model(model_name, params, eps):
    if model_name == "swift":
        return swift(eps, params["K"], params["eps_0"], params["n"])
    elif model_name == "voce":
        return voce(eps, params["sigma_sat"], params["sigma_y"], params["theta"])
    else:
        return hockett_sherby(eps, params["sigma_sat"], params["sigma_i"], params["m"], params["n"])


def get_calibration_data():
    tensile = load_json(os.path.join(DATA_DIR, "tensile_tests.json"))["0"]
    bulge = load_json(os.path.join(DATA_DIR, "bulge_test.json"))
    exp_strains = [d["plastic_strain"] for d in tensile] + [d["equiv_strain"] for d in bulge]
    exp_stresses = [d["true_stress"] for d in tensile] + [d["equiv_stress"] for d in bulge]
    return exp_strains, exp_stresses


def compute_model_rmses(params, exp_strains, exp_stresses):
    rmses = {}
    for model_name in ["swift", "voce", "hockett_sherby"]:
        pred = [eval_model(model_name, params[model_name], e) for e in exp_strains]
        rmses[model_name] = rmse(pred, exp_stresses)
    return rmses


# ============================================================
# Test 1: All output files exist and parse correctly
# ============================================================

class TestOutputFilesExist:
    def test_fitted_parameters_exists(self):
        path = os.path.join(OUTPUT_DIR, "fitted_parameters.json")
        assert os.path.isfile(path), f"Missing {path}"
        data = load_json(path)
        for model in ["swift", "voce", "hockett_sherby"]:
            assert model in data, f"Missing model '{model}' in fitted_parameters.json"

    def test_flow_curves_exists(self):
        path = os.path.join(OUTPUT_DIR, "flow_curves.json")
        assert os.path.isfile(path), f"Missing {path}"
        data = load_json(path)
        assert "strains" in data
        for model in ["swift", "voce", "hockett_sherby"]:
            assert model in data

    def test_blended_model_exists(self):
        path = os.path.join(OUTPUT_DIR, "blended_model.json")
        assert os.path.isfile(path), f"Missing {path}"
        data = load_json(path)
        assert "weights" in data
        assert "rmse" in data
        assert "stresses_at_eval_strains" in data
        for model in ["swift", "voce", "hockett_sherby"]:
            assert model in data["weights"], f"Missing weight for '{model}'"

    def test_hill48_parameters_exists(self):
        path = os.path.join(OUTPUT_DIR, "hill48_parameters.json")
        assert os.path.isfile(path), f"Missing {path}"
        data = load_json(path)
        for param in ["F", "G", "H", "N"]:
            assert param in data, f"Missing param '{param}'"

    def test_yield_locus_exists(self):
        path = os.path.join(OUTPUT_DIR, "yield_locus.csv")
        assert os.path.isfile(path), f"Missing {path}"
        with open(path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 360, f"Expected 360 rows, got {len(rows)}"
        assert "angle" in rows[0]
        assert "sigma_1" in rows[0]
        assert "sigma_2" in rows[0]

    def test_directional_properties_exists(self):
        path = os.path.join(OUTPUT_DIR, "directional_properties.json")
        assert os.path.isfile(path), f"Missing {path}"
        data = load_json(path)
        for key in ["angles", "normalized_yield_stress", "predicted_r_values", "r_value_errors"]:
            assert key in data, f"Missing key '{key}' in directional_properties.json"
        assert len(data["angles"]) == 5
        assert len(data["normalized_yield_stress"]) == 5
        assert len(data["predicted_r_values"]) == 5
        assert len(data["r_value_errors"]) == 5

    def test_anisotropic_flow_curves_exists(self):
        path = os.path.join(OUTPUT_DIR, "anisotropic_flow_curves.json")
        assert os.path.isfile(path), f"Missing {path}"
        data = load_json(path)
        for key in ["best_model", "yield_stress_ratios", "predicted_45", "predicted_90",
                     "measured_45_stress", "measured_45_strain",
                     "measured_90_stress", "measured_90_strain",
                     "rmse_45", "rmse_90"]:
            assert key in data, f"Missing key '{key}' in anisotropic_flow_curves.json"
        assert "45" in data["yield_stress_ratios"]
        assert "90" in data["yield_stress_ratios"]

    def test_benchmark_scores_exists(self):
        path = os.path.join(OUTPUT_DIR, "benchmark_scores.json")
        assert os.path.isfile(path), f"Missing {path}"
        data = load_json(path)
        assert "normalization_factors" in data
        assert "team_scores" in data
        assert "ranking" in data


# ============================================================
# Test 2: Fitted parameters produce accurate flow curves
# ============================================================

class TestHardeningLawFitting:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.params = load_json(os.path.join(OUTPUT_DIR, "fitted_parameters.json"))
        self.exp_strains, self.exp_stresses = get_calibration_data()

    def test_swift_fit_accuracy(self):
        p = self.params["swift"]
        pred = [swift(e, p["K"], p["eps_0"], p["n"]) for e in self.exp_strains]
        err = rmse(pred, self.exp_stresses)
        assert err < 40.0, f"Swift RMSE = {err:.2f} MPa, expected < 40.0"

    def test_voce_fit_accuracy(self):
        p = self.params["voce"]
        pred = [voce(e, p["sigma_sat"], p["sigma_y"], p["theta"]) for e in self.exp_strains]
        err = rmse(pred, self.exp_stresses)
        assert err < 20.0, f"Voce RMSE = {err:.2f} MPa, expected < 20.0"

    def test_hockett_sherby_fit_accuracy(self):
        p = self.params["hockett_sherby"]
        pred = [hockett_sherby(e, p["sigma_sat"], p["sigma_i"], p["m"], p["n"]) for e in self.exp_strains]
        err = rmse(pred, self.exp_stresses)
        assert err < 3.0, f"Hockett-Sherby RMSE = {err:.2f} MPa, expected < 3.0"

    def test_swift_parameters_reasonable(self):
        p = self.params["swift"]
        assert 800 < p["K"] < 2000, f"Swift K={p['K']} out of range"
        assert 0 < p["eps_0"] < 0.1, f"Swift eps_0={p['eps_0']} out of range"
        assert 0.05 < p["n"] < 0.5, f"Swift n={p['n']} out of range"

    def test_voce_parameters_reasonable(self):
        p = self.params["voce"]
        assert 800 < p["sigma_sat"] < 1200, f"Voce sigma_sat={p['sigma_sat']} out of range"
        assert 300 < p["sigma_y"] < 600, f"Voce sigma_y={p['sigma_y']} out of range"
        assert 1 < p["theta"] < 100, f"Voce theta={p['theta']} out of range"

    def test_hockett_sherby_parameters_reasonable(self):
        p = self.params["hockett_sherby"]
        assert 900 < p["sigma_sat"] < 1200, f"HS sigma_sat={p['sigma_sat']} out of range"
        assert 300 < p["sigma_i"] < 600, f"HS sigma_i={p['sigma_i']} out of range"
        assert 1 < p["m"] < 30, f"HS m={p['m']} out of range"
        assert 0.1 < p["n"] < 2.0, f"HS n={p['n']} out of range"


# ============================================================
# Test 3: Flow curves consistency
# ============================================================

class TestFlowCurves:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.fc = load_json(os.path.join(OUTPUT_DIR, "flow_curves.json"))
        self.params = load_json(os.path.join(OUTPUT_DIR, "fitted_parameters.json"))

    def test_correct_strain_points(self):
        expected = [0.001, 0.005, 0.01, 0.02, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50]
        assert len(self.fc["strains"]) == 10
        for e, a in zip(expected, self.fc["strains"]):
            assert abs(e - a) < 1e-6

    def test_flow_curves_match_parameters(self):
        """Verify flow curve values are consistent with fitted parameters."""
        strains = self.fc["strains"]
        p_sw = self.params["swift"]
        for i, eps in enumerate(strains):
            expected = swift(eps, p_sw["K"], p_sw["eps_0"], p_sw["n"])
            actual = self.fc["swift"][i]
            assert abs(expected - actual) < 0.1, \
                f"Swift mismatch at eps={eps}: expected {expected:.2f}, got {actual:.2f}"

        p_vo = self.params["voce"]
        for i, eps in enumerate(strains):
            expected = voce(eps, p_vo["sigma_sat"], p_vo["sigma_y"], p_vo["theta"])
            actual = self.fc["voce"][i]
            assert abs(expected - actual) < 0.1

        p_hs = self.params["hockett_sherby"]
        for i, eps in enumerate(strains):
            expected = hockett_sherby(eps, p_hs["sigma_sat"], p_hs["sigma_i"], p_hs["m"], p_hs["n"])
            actual = self.fc["hockett_sherby"][i]
            assert abs(expected - actual) < 0.1

    def test_monotonic_increase(self):
        """All hardening curves must be monotonically increasing."""
        for model in ["swift", "voce", "hockett_sherby"]:
            stresses = self.fc[model]
            for i in range(1, len(stresses)):
                assert stresses[i] > stresses[i - 1], \
                    f"{model} not monotonic at index {i}: {stresses[i-1]:.2f} -> {stresses[i]:.2f}"


# ============================================================
# Test 4: Blended hardening model
# ============================================================

class TestBlendedModel:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.blend = load_json(os.path.join(OUTPUT_DIR, "blended_model.json"))
        self.params = load_json(os.path.join(OUTPUT_DIR, "fitted_parameters.json"))
        self.exp_strains, self.exp_stresses = get_calibration_data()

    def test_weights_sum_to_one(self):
        w = self.blend["weights"]
        total = w["swift"] + w["voce"] + w["hockett_sherby"]
        assert abs(total - 1.0) < 1e-6, f"Weights sum to {total}, expected 1.0"

    def test_weights_non_negative(self):
        for name, w in self.blend["weights"].items():
            assert w >= -1e-8, f"Weight for {name} is negative: {w}"

    def test_rmse_at_least_as_good_as_best_individual(self):
        """Blend RMSE must not exceed the best individual model's RMSE."""
        model_rmses = compute_model_rmses(self.params, self.exp_strains, self.exp_stresses)
        best_individual = min(model_rmses.values())
        assert self.blend["rmse"] <= best_individual + 0.05, \
            f"Blend RMSE {self.blend['rmse']:.4f} exceeds best individual {best_individual:.4f}"

    def test_stresses_match_weighted_sum(self):
        """Verify stresses are consistent with weights and individual model predictions."""
        w = self.blend["weights"]
        strains = [0.001, 0.005, 0.01, 0.02, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50]

        for i, eps in enumerate(strains):
            s_sw = eval_model("swift", self.params["swift"], eps)
            s_vo = eval_model("voce", self.params["voce"], eps)
            s_hs = eval_model("hockett_sherby", self.params["hockett_sherby"], eps)
            expected = w["swift"] * s_sw + w["voce"] * s_vo + w["hockett_sherby"] * s_hs
            actual = self.blend["stresses_at_eval_strains"][i]
            assert abs(expected - actual) < 0.5, \
                f"Blend stress mismatch at eps={eps}: expected {expected:.2f}, got {actual:.2f}"

    def test_rmse_computation_correct(self):
        """Verify reported RMSE matches recomputation from weights and data."""
        w = self.blend["weights"]
        pred = []
        for eps in self.exp_strains:
            s_sw = eval_model("swift", self.params["swift"], eps)
            s_vo = eval_model("voce", self.params["voce"], eps)
            s_hs = eval_model("hockett_sherby", self.params["hockett_sherby"], eps)
            pred.append(w["swift"] * s_sw + w["voce"] * s_vo + w["hockett_sherby"] * s_hs)
        computed_rmse = rmse(pred, self.exp_stresses)
        assert abs(computed_rmse - self.blend["rmse"]) < 0.1, \
            f"Reported RMSE {self.blend['rmse']:.4f} != computed {computed_rmse:.4f}"

    def test_monotonic_increase(self):
        """Blended curve must be monotonically increasing (convex combo of monotonic curves)."""
        stresses = self.blend["stresses_at_eval_strains"]
        for i in range(1, len(stresses)):
            assert stresses[i] > stresses[i - 1], \
                f"Blended curve not monotonic at index {i}: {stresses[i-1]:.2f} -> {stresses[i]:.2f}"

    def test_ten_eval_strains(self):
        assert len(self.blend["stresses_at_eval_strains"]) == 10


# ============================================================
# Test 5: Hill48 parameters
# ============================================================

class TestHill48:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.hill48 = load_json(os.path.join(OUTPUT_DIR, "hill48_parameters.json"))
        self.mat = load_json(os.path.join(DATA_DIR, "material_params.json"))

    def test_hill48_from_r_values(self):
        """Verify Hill48 params match analytical R-value formulas."""
        r0 = self.mat["r_values"]["0"]
        r45 = self.mat["r_values"]["45"]
        r90 = self.mat["r_values"]["90"]

        G_exp = 1.0 / (1 + r0)
        H_exp = r0 / (1 + r0)
        F_exp = r0 / (r90 * (1 + r0))
        N_exp = (r0 + r90) * (1 + 2 * r45) / (2 * r90 * (1 + r0))

        assert abs(self.hill48["F"] - F_exp) < 1e-4, \
            f"F: expected {F_exp:.6f}, got {self.hill48['F']:.6f}"
        assert abs(self.hill48["G"] - G_exp) < 1e-4, \
            f"G: expected {G_exp:.6f}, got {self.hill48['G']:.6f}"
        assert abs(self.hill48["H"] - H_exp) < 1e-4, \
            f"H: expected {H_exp:.6f}, got {self.hill48['H']:.6f}"
        assert abs(self.hill48["N"] - N_exp) < 1e-4, \
            f"N: expected {N_exp:.6f}, got {self.hill48['N']:.6f}"

    def test_gh_sum_positive(self):
        """G + H must be positive (normalization convention)."""
        assert self.hill48["G"] + self.hill48["H"] > 0

    def test_all_positive(self):
        """All Hill48 parameters must be positive for physical meaning."""
        for p in ["F", "G", "H", "N"]:
            assert self.hill48[p] > 0, f"Hill48 {p} must be positive"


# ============================================================
# Test 6: Yield locus
# ============================================================

class TestYieldLocus:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.hill48 = load_json(os.path.join(OUTPUT_DIR, "hill48_parameters.json"))
        with open(os.path.join(OUTPUT_DIR, "yield_locus.csv")) as f:
            reader = csv.DictReader(f)
            self.locus = list(reader)

    def test_360_points(self):
        assert len(self.locus) == 360

    def test_points_on_surface(self):
        """Each yield locus point must satisfy the Hill48 equation."""
        F = self.hill48["F"]
        G = self.hill48["G"]
        H = self.hill48["H"]

        for row in self.locus:
            s1 = float(row["sigma_1"])
            s2 = float(row["sigma_2"])
            # Hill48 plane stress: F*s2^2 + G*s1^2 + H*(s1-s2)^2 = 1
            val = F * s2**2 + G * s1**2 + H * (s1 - s2)**2
            assert abs(val - 1.0) < 1e-4, \
                f"Hill48 surface violation at angle={row['angle']}: " \
                f"F*s2^2 + G*s1^2 + H*(s1-s2)^2 = {val:.6f}, expected 1.0"

    def test_symmetry(self):
        """Yield locus should have expected symmetry properties."""
        row_0 = self.locus[0]
        s1_0 = float(row_0["sigma_1"])
        s2_0 = float(row_0["sigma_2"])
        assert abs(s2_0) < 0.01, f"At angle=0, sigma_2 should be ~0, got {s2_0}"
        assert s1_0 > 0, f"At angle=0, sigma_1 should be positive"

    def test_biaxial_point(self):
        """At 45 deg, sigma_1 = sigma_2 (equibiaxial)."""
        row_45 = self.locus[45]
        s1 = float(row_45["sigma_1"])
        s2 = float(row_45["sigma_2"])
        assert abs(s1 - s2) < 0.01, \
            f"At 45 deg, expected sigma_1 ~ sigma_2, got {s1:.4f}, {s2:.4f}"


# ============================================================
# Test 7: Directional properties
# ============================================================

class TestDirectionalProperties:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.dp = load_json(os.path.join(OUTPUT_DIR, "directional_properties.json"))
        self.mat = load_json(os.path.join(DATA_DIR, "material_params.json"))
        self.hill48 = load_json(os.path.join(OUTPUT_DIR, "hill48_parameters.json"))

    def test_correct_angles(self):
        expected_angles = [0.0, 22.5, 45.0, 67.5, 90.0]
        assert len(self.dp["angles"]) == 5
        for e, a in zip(expected_angles, self.dp["angles"]):
            assert abs(e - a) < 0.01, f"Expected angle {e}, got {a}"

    def test_yield_stress_at_zero(self):
        """Normalized yield stress at 0 deg must be 1.0."""
        assert abs(self.dp["normalized_yield_stress"][0] - 1.0) < 1e-6, \
            f"Yield stress at 0 deg = {self.dp['normalized_yield_stress'][0]}, expected 1.0"

    def test_yield_stress_range(self):
        """All normalized yield stresses must be in physical range."""
        for i, ys in enumerate(self.dp["normalized_yield_stress"]):
            assert 0.9 < ys < 1.15, \
                f"Yield stress at angle {self.dp['angles'][i]} = {ys}, out of range [0.9, 1.15]"

    def test_r_values_at_calibration_angles(self):
        """At 0, 45, 90 deg the predicted R-values must match measured."""
        measured = self.mat["r_values"]
        assert abs(self.dp["predicted_r_values"][0] - measured["0"]) < 1e-4, \
            f"R(0): predicted {self.dp['predicted_r_values'][0]}, measured {measured['0']}"
        assert abs(self.dp["predicted_r_values"][2] - measured["45"]) < 1e-4, \
            f"R(45): predicted {self.dp['predicted_r_values'][2]}, measured {measured['45']}"
        assert abs(self.dp["predicted_r_values"][4] - measured["90"]) < 1e-4, \
            f"R(90): predicted {self.dp['predicted_r_values'][4]}, measured {measured['90']}"

    def test_r_values_range(self):
        """All predicted R-values must be positive and reasonable."""
        for i, rv in enumerate(self.dp["predicted_r_values"]):
            assert 0.5 < rv < 2.0, \
                f"R-value at {self.dp['angles'][i]} deg = {rv}, out of range [0.5, 2.0]"

    def test_r_value_errors(self):
        """R-value errors must be absolute differences from measured."""
        measured = self.mat["r_values"]
        angles_str = ["0", "22.5", "45", "67.5", "90"]
        for i, ang_str in enumerate(angles_str):
            expected_error = abs(self.dp["predicted_r_values"][i] - measured[ang_str])
            actual_error = self.dp["r_value_errors"][i]
            assert abs(expected_error - actual_error) < 1e-6, \
                f"R-value error at {ang_str} deg: expected {expected_error:.6f}, got {actual_error:.6f}"

    def test_predicted_r_values_from_hill48(self):
        """Verify R-value predictions are consistent with Hill48 parameters."""
        F = self.hill48["F"]
        G = self.hill48["G"]
        H = self.hill48["H"]
        N = self.hill48["N"]

        for i, angle_deg in enumerate(self.dp["angles"]):
            theta = math.radians(angle_deg)
            sin2 = math.sin(theta) ** 2
            cos2 = math.cos(theta) ** 2
            numerator = H + (2 * N - F - G - 4 * H) * sin2 * cos2
            denominator = F * sin2 + G * cos2
            if denominator > 1e-10:
                expected_r = numerator / denominator
                actual_r = self.dp["predicted_r_values"][i]
                assert abs(expected_r - actual_r) < 1e-4, \
                    f"R-value at {angle_deg} deg: expected {expected_r:.6f}, got {actual_r:.6f}"

    def test_yield_stress_from_hill48(self):
        """Verify normalized yield stress is consistent with Hill48."""
        F = self.hill48["F"]
        G = self.hill48["G"]
        H = self.hill48["H"]
        N = self.hill48["N"]

        for i, angle_deg in enumerate(self.dp["angles"]):
            theta = math.radians(angle_deg)
            sin2 = math.sin(theta) ** 2
            cos2 = math.cos(theta) ** 2
            sin4 = sin2 ** 2
            cos4 = cos2 ** 2

            denom_term = F * sin4 + G * cos4 + H * (cos2 - sin2) ** 2 + 2 * N * sin2 * cos2
            expected_ratio = math.sqrt((G + H) / denom_term)
            actual_ratio = self.dp["normalized_yield_stress"][i]
            assert abs(expected_ratio - actual_ratio) < 1e-4, \
                f"Yield ratio at {angle_deg} deg: expected {expected_ratio:.6f}, got {actual_ratio:.6f}"


# ============================================================
# Test 8: Anisotropic flow curves (cross-validation)
# ============================================================

class TestAnisotropicFlowCurves:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.afc = load_json(os.path.join(OUTPUT_DIR, "anisotropic_flow_curves.json"))
        self.params = load_json(os.path.join(OUTPUT_DIR, "fitted_parameters.json"))
        self.hill48 = load_json(os.path.join(OUTPUT_DIR, "hill48_parameters.json"))
        self.tensile = load_json(os.path.join(DATA_DIR, "tensile_tests.json"))

    def test_best_model_is_lowest_rmse(self):
        """The best_model field must identify the model with lowest calibration RMSE."""
        exp_strains, exp_stresses = get_calibration_data()
        model_rmses = compute_model_rmses(self.params, exp_strains, exp_stresses)
        expected_best = min(model_rmses, key=model_rmses.get)
        assert self.afc["best_model"] == expected_best, \
            f"Best model should be {expected_best}, got {self.afc['best_model']}"

    def test_yield_stress_ratios_from_hill48(self):
        """Yield stress ratios must be consistent with Hill48 parameters."""
        F = self.hill48["F"]
        G = self.hill48["G"]
        H = self.hill48["H"]
        N = self.hill48["N"]

        for angle_str, angle_deg in [("45", 45.0), ("90", 90.0)]:
            theta = math.radians(angle_deg)
            sin2 = math.sin(theta) ** 2
            cos2 = math.cos(theta) ** 2
            sin4 = sin2 ** 2
            cos4 = cos2 ** 2
            A = F * sin4 + G * cos4 + H * (cos2 - sin2) ** 2 + 2 * N * sin2 * cos2
            expected_ratio = math.sqrt((G + H) / A)
            actual_ratio = self.afc["yield_stress_ratios"][angle_str]
            assert abs(expected_ratio - actual_ratio) < 1e-4, \
                f"Yield stress ratio at {angle_str} deg: expected {expected_ratio:.6f}, got {actual_ratio}"

    def test_predicted_values_consistent_with_model(self):
        """Predicted values must use best model + ratio + strain transformation."""
        best_model = self.afc["best_model"]
        p = self.params[best_model]

        for angle_str in ["45", "90"]:
            ratio = self.afc["yield_stress_ratios"][angle_str]
            meas_strains = self.afc[f"measured_{angle_str}_strain"]
            predicted = self.afc[f"predicted_{angle_str}"]

            assert len(predicted) == len(meas_strains), \
                f"Predicted length mismatch at {angle_str} deg"

            for i, eps_axial in enumerate(meas_strains):
                eps_equiv = ratio * eps_axial
                expected = ratio * eval_model(best_model, p, eps_equiv)
                actual = predicted[i]
                assert abs(expected - actual) < 0.5, \
                    f"Prediction at {angle_str} deg, strain={eps_axial:.4f}: " \
                    f"expected {expected:.2f}, got {actual:.2f}"

    def test_measured_data_matches_input(self):
        """Measured data must match the actual tensile test input data."""
        for angle_str in ["45", "90"]:
            input_data = self.tensile[angle_str]
            meas_strains = self.afc[f"measured_{angle_str}_strain"]
            meas_stresses = self.afc[f"measured_{angle_str}_stress"]

            assert len(meas_strains) == len(input_data), \
                f"Data length mismatch at {angle_str} deg"
            for i, d in enumerate(input_data):
                assert abs(meas_strains[i] - d["plastic_strain"]) < 1e-6
                assert abs(meas_stresses[i] - d["true_stress"]) < 1e-2

    def test_rmse_threshold(self):
        """RMSE for anisotropic predictions must be below 50 MPa."""
        for angle_str in ["45", "90"]:
            r = self.afc[f"rmse_{angle_str}"]
            assert r < 50.0, f"RMSE at {angle_str} deg = {r:.2f}, expected < 50.0"

    def test_rmse_computation_correct(self):
        """Verify reported RMSE matches recomputation from predicted and measured."""
        for angle_str in ["45", "90"]:
            predicted = self.afc[f"predicted_{angle_str}"]
            measured = self.afc[f"measured_{angle_str}_stress"]
            expected_rmse = math.sqrt(
                sum((p - m) ** 2 for p, m in zip(predicted, measured)) / len(measured)
            )
            reported = self.afc[f"rmse_{angle_str}"]
            assert abs(expected_rmse - reported) < 0.5, \
                f"RMSE at {angle_str} deg: expected {expected_rmse:.4f}, reported {reported:.4f}"


# ============================================================
# Test 9: Benchmark scoring
# ============================================================

class TestBenchmarkScoring:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.scores = load_json(os.path.join(OUTPUT_DIR, "benchmark_scores.json"))
        self.gt = load_json(os.path.join(DATA_DIR, "ground_truth.json"))
        self.subs = load_json(os.path.join(DATA_DIR, "submissions.json"))

    def _compute_rmse(self, pred, actual):
        n = len(actual)
        return math.sqrt(sum((p - a) ** 2 for p, a in zip(pred, actual)) / n)

    def test_ranking_order(self):
        """Verify ranking is from best (lowest) to worst (highest) total score."""
        ranking = self.scores["ranking"]
        scores = self.scores["team_scores"]
        for i in range(len(ranking) - 1):
            assert scores[ranking[i]] <= scores[ranking[i + 1]], \
                f"Ranking violation: {ranking[i]}({scores[ranking[i]]:.4f}) > " \
                f"{ranking[i+1]}({scores[ranking[i+1]]:.4f})"

    def test_all_teams_present(self):
        teams = ["team_A", "team_B", "team_C", "team_D", "team_E"]
        for t in teams:
            assert t in self.scores["team_scores"], f"Missing team {t} in scores"
        assert len(self.scores["ranking"]) == 5

    def test_normalization_factors_correct(self):
        """Verify normalization factors are the mean RMSE across teams."""
        configs = ["70", "110", "230"]
        teams = ["team_A", "team_B", "team_C", "team_D", "team_E"]

        for config in configs:
            gt = self.gt[config]

            # Force
            force_rmses = []
            for team in teams:
                sub = self.subs[team][config]
                force_rmses.append(self._compute_rmse(sub["force"], gt["force"]))
            expected_norm = sum(force_rmses) / len(force_rmses)
            actual_norm = self.scores["normalization_factors"][config]["force"]
            assert abs(expected_norm - actual_norm) < 1e-4, \
                f"Force norm factor mismatch for config {config}: " \
                f"expected {expected_norm:.6f}, got {actual_norm:.6f}"

            # Major strain
            major_rmses = []
            for team in teams:
                sub = self.subs[team][config]
                xz = self._compute_rmse(sub["major_strain_xz"], gt["major_strain_xz"])
                yz = self._compute_rmse(sub["major_strain_yz"], gt["major_strain_yz"])
                major_rmses.append((xz + yz) / 2)
            expected_norm = sum(major_rmses) / len(major_rmses)
            actual_norm = self.scores["normalization_factors"][config]["major_strain"]
            assert abs(expected_norm - actual_norm) < 1e-4, \
                f"Major strain norm factor mismatch for config {config}"

            # Minor strain
            minor_rmses = []
            for team in teams:
                sub = self.subs[team][config]
                xz = self._compute_rmse(sub["minor_strain_xz"], gt["minor_strain_xz"])
                yz = self._compute_rmse(sub["minor_strain_yz"], gt["minor_strain_yz"])
                minor_rmses.append((xz + yz) / 2)
            expected_norm = sum(minor_rmses) / len(minor_rmses)
            actual_norm = self.scores["normalization_factors"][config]["minor_strain"]
            assert abs(expected_norm - actual_norm) < 1e-4, \
                f"Minor strain norm factor mismatch for config {config}"

    def test_total_scores_correct(self):
        """Verify total scores match the normalized RMSE methodology."""
        configs = ["70", "110", "230"]
        teams = ["team_A", "team_B", "team_C", "team_D", "team_E"]
        metrics = ["force", "major_strain", "minor_strain"]

        # Compute raw RMSE
        raw = {}
        for team in teams:
            raw[team] = {}
            for config in configs:
                gt_c = self.gt[config]
                sub_c = self.subs[team][config]
                force_rmse = self._compute_rmse(sub_c["force"], gt_c["force"])
                major_xz = self._compute_rmse(sub_c["major_strain_xz"], gt_c["major_strain_xz"])
                major_yz = self._compute_rmse(sub_c["major_strain_yz"], gt_c["major_strain_yz"])
                minor_xz = self._compute_rmse(sub_c["minor_strain_xz"], gt_c["minor_strain_xz"])
                minor_yz = self._compute_rmse(sub_c["minor_strain_yz"], gt_c["minor_strain_yz"])
                raw[team][config] = {
                    "force": force_rmse,
                    "major_strain": (major_xz + major_yz) / 2,
                    "minor_strain": (minor_xz + minor_yz) / 2
                }

        # Normalization factors
        nf = {}
        for config in configs:
            nf[config] = {}
            for metric in metrics:
                nf[config][metric] = sum(raw[t][config][metric] for t in teams) / len(teams)

        # Total scores
        for team in teams:
            total = 0.0
            for metric in metrics:
                avg_norm = sum(raw[team][c][metric] / nf[c][metric] for c in configs) / 3
                total += avg_norm

            reported = self.scores["team_scores"][team]
            assert abs(total - reported) < 1e-3, \
                f"Total score mismatch for {team}: expected {total:.6f}, got {reported:.6f}"

    def test_correct_ranking(self):
        """team_A should be ranked first (lowest score), team_E last."""
        assert self.scores["ranking"][0] == "team_A", \
            f"Expected team_A ranked first, got {self.scores['ranking'][0]}"
        assert self.scores["ranking"][-1] == "team_E", \
            f"Expected team_E ranked last, got {self.scores['ranking'][-1]}"
