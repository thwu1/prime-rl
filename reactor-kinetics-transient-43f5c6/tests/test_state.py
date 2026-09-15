
"""Tests for coupled point kinetics + thermal feedback reactor transient simulator
with nonlinear spectral correction from Fortran cross-section library."""

import csv
import ctypes
import json
import math
import os
import subprocess

import numpy as np
import pytest

RESULTS_DIR = "/app/results"
DATA_DIR = "/app/data"

# ---- Correct parameter values (after unit conversion from reactor.inp) ----
# These embed the expected values so tests verify correct parsing + unit handling.

BETA = [0.000215, 0.001424, 0.001274, 0.002568, 0.000748, 0.000273]
LAMBDA = [0.0124, 0.0305, 0.111, 0.301, 1.14, 3.01]
GEN_TIME = 2.0e-5
BETA_TOTAL = sum(BETA)  # 0.006502

P0 = 50000.0  # 50 kW -> 50000 W
FUEL_CP = 600.0
MOD_CP = 4000.0
H_FM = 100.0
H_MC = 2500.0
T_INLET = 560.0  # 286.85 C -> 560.0 K
ALPHA_F = -3.0e-5
ALPHA_M = -1.0e-4

# Spectral correction coefficients from the Fortran library
KAPPA_F = -6.5e-8    # [dk/k/K^2] fuel Doppler second-order
KAPPA_M = -2.7e-7    # [dk/k/K^2] moderator density second-order
KAPPA_FM = 3.5e-8    # [dk/k/K^2] fuel-moderator spectral coupling

T_M0 = T_INLET + P0 / H_MC  # 580.0 K
T_F0 = T_M0 + P0 / H_FM  # 1080.0 K

SCENARIO_NAMES = [
    "step_half_dollar",
    "step_super_prompt",
    "ramp_then_hold",
    "oscillatory",
    "scram",
    "rod_calibration",
]

CSV_COLUMNS = [
    "time_s",
    "n_relative",
    "T_fuel_K",
    "T_moderator_K",
    "rho_total",
    "rho_external",
    "rho_feedback",
]

MEASURED_PROMPT_DROP_RATIO = 0.13


# ---- Utilities ----


def load_csv(name):
    path = os.path.join(RESULTS_DIR, f"scenario_{name}.csv")
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        return [{k: float(v) for k, v in row.items()} for row in reader]


def load_summary():
    with open(os.path.join(RESULTS_DIR, "summary.json"), "r") as f:
        return json.load(f)


def load_analysis():
    with open(os.path.join(RESULTS_DIR, "analysis.json"), "r") as f:
        return json.load(f)


def load_scenarios():
    with open(os.path.join(DATA_DIR, "scenarios.json"), "r") as f:
        return json.load(f)


def _compute_feedback_python(T_f, T_m):
    """Reference feedback computation using the nonlinear model."""
    dT_f = T_f - T_F0
    dT_m = T_m - T_M0
    return (ALPHA_F * dT_f + ALPHA_M * dT_m
            + KAPPA_F * dT_f * dT_f
            + KAPPA_M * dT_m * dT_m
            + KAPPA_FM * dT_f * dT_m)


def _nonlinear_equilibrium(rho_ext):
    """Solve for equilibrium power with nonlinear spectral feedback."""
    A_f = P0 * (1.0 / H_MC + 1.0 / H_FM)
    A_m = P0 / H_MC
    c_lin = ALPHA_F * A_f + ALPHA_M * A_m
    c_quad = KAPPA_F * A_f**2 + KAPPA_M * A_m**2 + KAPPA_FM * A_f * A_m
    disc = c_lin**2 - 4.0 * c_quad * rho_ext
    x = (-c_lin - math.sqrt(disc)) / (2.0 * c_quad)
    return 1.0 + x


def _linear_equilibrium(rho_ext):
    """Equilibrium with linear-only feedback (no spectral correction)."""
    c_lin = P0 * (ALPHA_F * (1.0 / H_MC + 1.0 / H_FM) + ALPHA_M / H_MC)
    return 1.0 - rho_ext / c_lin


def _solve_inhour_period_ref(rho):
    """Reference inhour equation solver (bisection, no scipy needed)."""

    def f(omega):
        val = GEN_TIME * omega
        for b, l in zip(BETA, LAMBDA):
            val += b * omega / (l + omega)
        return val - rho

    lo, hi = 1e-15, max(rho / GEN_TIME * 100, 1e8)
    while f(hi) < 0:
        hi *= 10
    for _ in range(300):
        mid = (lo + hi) / 2.0
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    return 1.0 / ((lo + hi) / 2.0)


def _expected_rod_worth():
    """Analytical rod worth from prompt jump relationship."""
    return BETA_TOTAL * (1.0 - 1.0 / MEASURED_PROMPT_DROP_RATIO)


# ---- File existence and format tests ----


class TestFileExistence:
    def test_summary_json_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "summary.json"))

    def test_analysis_json_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "analysis.json"))

    @pytest.mark.parametrize("name", SCENARIO_NAMES)
    def test_scenario_csv_exists(self, name):
        path = os.path.join(RESULTS_DIR, f"scenario_{name}.csv")
        assert os.path.isfile(path), f"Missing CSV for scenario {name}"


class TestCSVFormat:
    @pytest.mark.parametrize("name", SCENARIO_NAMES)
    def test_csv_has_correct_columns(self, name):
        path = os.path.join(RESULTS_DIR, f"scenario_{name}.csv")
        with open(path, "r") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
        for col in CSV_COLUMNS:
            assert col in header, f"Missing column '{col}' in {name}"

    @pytest.mark.parametrize("name", SCENARIO_NAMES)
    def test_csv_has_enough_rows(self, name):
        scenarios = load_scenarios()
        scenario = next(s for s in scenarios if s["name"] == name)
        min_points = scenario["n_output_points"]
        rows = load_csv(name)
        assert len(rows) >= min_points, (
            f"Scenario {name}: expected >= {min_points} rows, got {len(rows)}"
        )


class TestSummaryFormat:
    def test_summary_has_all_scenarios(self):
        summary = load_summary()
        for name in SCENARIO_NAMES:
            assert name in summary, f"Missing scenario '{name}' in summary"

    def test_summary_has_required_fields(self):
        summary = load_summary()
        required_fields = [
            "peak_power_relative",
            "time_of_peak_s",
            "final_power_relative",
            "final_fuel_temp_K",
            "final_mod_temp_K",
            "final_reactivity_total",
        ]
        for name in SCENARIO_NAMES:
            for field in required_fields:
                assert field in summary[name], (
                    f"Missing field '{field}' in summary['{name}']"
                )


class TestAnalysisFormat:
    def test_analysis_has_step_half_dollar(self):
        analysis = load_analysis()
        assert "step_half_dollar" in analysis
        assert "inhour_period_s" in analysis["step_half_dollar"]

    def test_analysis_has_step_super_prompt(self):
        analysis = load_analysis()
        assert "step_super_prompt" in analysis
        assert "inhour_period_s" in analysis["step_super_prompt"]

    def test_analysis_has_rod_calibration(self):
        analysis = load_analysis()
        assert "rod_calibration" in analysis
        assert "rod_worth_dk_k" in analysis["rod_calibration"]


# ---- Physics constraint tests ----


class TestPhysicsConstraints:
    @pytest.mark.parametrize("name", SCENARIO_NAMES)
    def test_power_is_positive(self, name):
        rows = load_csv(name)
        for row in rows:
            assert row["n_relative"] > 0, (
                f"Scenario {name}: negative power at t={row['time_s']}"
            )

    @pytest.mark.parametrize("name", SCENARIO_NAMES)
    def test_temperatures_physical(self, name):
        rows = load_csv(name)
        for row in rows:
            assert 300 < row["T_fuel_K"] < 3000, (
                f"Scenario {name}: unphysical fuel temp {row['T_fuel_K']} "
                f"at t={row['time_s']}"
            )
            assert 300 < row["T_moderator_K"] < 3000, (
                f"Scenario {name}: unphysical mod temp {row['T_moderator_K']} "
                f"at t={row['time_s']}"
            )

    @pytest.mark.parametrize("name", SCENARIO_NAMES)
    def test_fuel_hotter_than_moderator(self, name):
        rows = load_csv(name)
        for row in rows:
            if row["n_relative"] > 0.01:
                assert row["T_fuel_K"] >= row["T_moderator_K"] - 1.0, (
                    f"Scenario {name}: fuel cooler than moderator "
                    f"at t={row['time_s']}"
                )

    @pytest.mark.parametrize("name", SCENARIO_NAMES)
    def test_reactivity_balance(self, name):
        rows = load_csv(name)
        for row in rows:
            rho_sum = row["rho_external"] + row["rho_feedback"]
            assert abs(row["rho_total"] - rho_sum) < 1e-8, (
                f"Scenario {name}: reactivity balance violated at t={row['time_s']}"
            )

    @pytest.mark.parametrize("name", SCENARIO_NAMES)
    def test_time_monotonic(self, name):
        rows = load_csv(name)
        times = [r["time_s"] for r in rows]
        for i in range(1, len(times)):
            assert times[i] > times[i - 1], (
                f"Scenario {name}: non-monotonic time at index {i}"
            )


# ---- Initial condition tests ----


class TestInitialConditions:
    def test_initial_power_is_unity(self):
        for name in SCENARIO_NAMES:
            rows = load_csv(name)
            assert abs(rows[0]["n_relative"] - 1.0) < 0.01, (
                f"Scenario {name}: initial power {rows[0]['n_relative']} != 1.0"
            )

    def test_initial_temperatures_consistent(self):
        """Initial temperatures must match thermal balance with correct units."""
        for name in SCENARIO_NAMES:
            rows = load_csv(name)
            T_f = rows[0]["T_fuel_K"]
            T_m = rows[0]["T_moderator_K"]
            assert abs(T_f - T_F0) < 1.0, (
                f"Scenario {name}: initial T_fuel {T_f:.1f} != expected {T_F0:.1f} "
                f"(check power unit conversion: 50 kW = 50000 W)"
            )
            assert abs(T_m - T_M0) < 1.0, (
                f"Scenario {name}: initial T_mod {T_m:.1f} != expected {T_M0:.1f} "
                f"(check temperature unit conversion: 286.85 C = 560.0 K)"
            )

    def test_initial_reactivity_near_zero(self):
        for name in SCENARIO_NAMES:
            rows = load_csv(name)
            assert abs(rows[0]["rho_feedback"]) < 1e-6, (
                f"Scenario {name}: initial feedback reactivity "
                f"{rows[0]['rho_feedback']} should be ~0"
            )


# ---- Spectral correction (Fortran library) tests ----


class TestSpectralCorrection:
    """Verify the Fortran spectral feedback library is compiled and used."""

    @pytest.fixture(scope="class")
    def fortran_lib(self):
        """Independently compile and load the Fortran spectral feedback library."""
        so_path = "/tmp/test_spectral_feedback.so"
        result = subprocess.run(
            ["gfortran", "-shared", "-fPIC", "-o", so_path,
             "/app/data/spectral_feedback.f90"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"Fortran compilation failed: {result.stderr.decode()}"
        )
        lib = ctypes.CDLL(so_path)

        lib.compute_feedback.argtypes = [
            ctypes.c_double, ctypes.c_double,
            ctypes.c_double, ctypes.c_double,
            ctypes.c_double, ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
        ]
        lib.compute_feedback.restype = None

        lib.get_spectral_coefficients.argtypes = [
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
        ]
        lib.get_spectral_coefficients.restype = None

        return lib

    def test_fortran_source_compiles(self, fortran_lib):
        """The spectral feedback Fortran source must compile successfully."""
        assert fortran_lib is not None

    def test_spectral_coefficients_nonzero(self, fortran_lib):
        """The Fortran library must export nonzero spectral correction coefficients."""
        kf = ctypes.c_double(0.0)
        km = ctypes.c_double(0.0)
        kfm = ctypes.c_double(0.0)
        fortran_lib.get_spectral_coefficients(
            ctypes.byref(kf), ctypes.byref(km), ctypes.byref(kfm)
        )
        assert kf.value != 0.0
        assert km.value != 0.0
        assert kfm.value != 0.0

    def test_solver_feedback_matches_fortran_library(self, fortran_lib):
        """Solver's rho_feedback must match the Fortran library computation at
        multiple points in the step_half_dollar transient."""
        rows = load_csv("step_half_dollar")
        check_indices = [len(rows) // 4, len(rows) // 2, 3 * len(rows) // 4, -1]
        for idx in check_indices:
            row = rows[idx]
            T_f = row["T_fuel_K"]
            T_m = row["T_moderator_K"]
            rho_fb_solver = row["rho_feedback"]

            rho_out = ctypes.c_double(0.0)
            fortran_lib.compute_feedback(
                ctypes.c_double(T_f), ctypes.c_double(T_m),
                ctypes.c_double(T_F0), ctypes.c_double(T_M0),
                ctypes.c_double(ALPHA_F), ctypes.c_double(ALPHA_M),
                ctypes.byref(rho_out),
            )

            assert abs(rho_fb_solver - rho_out.value) < 1e-5, (
                f"Feedback mismatch at t={row['time_s']:.2f}s: "
                f"solver={rho_fb_solver:.8f}, Fortran={rho_out.value:.8f}"
            )

    def test_nonlinear_not_linear_equilibrium(self):
        """Equilibrium must match the nonlinear (spectral-corrected) prediction,
        not the simpler linear-only model."""
        summary = load_summary()
        n_final = summary["step_half_dollar"]["final_power_relative"]

        rho_ext = 0.5 * BETA_TOTAL
        n_linear = _linear_equilibrium(rho_ext)
        n_nonlinear = _nonlinear_equilibrium(rho_ext)

        err_lin = abs(n_final - n_linear)
        err_nl = abs(n_final - n_nonlinear)
        assert err_nl < err_lin, (
            f"Result {n_final:.5f} closer to linear model {n_linear:.5f} "
            f"than nonlinear {n_nonlinear:.5f} — spectral correction not applied"
        )

    def test_super_prompt_feedback_matches_fortran(self, fortran_lib):
        """Super-prompt scenario feedback must also match the Fortran library,
        verifying that large temperature excursions use nonlinear model."""
        rows = load_csv("step_super_prompt")
        row = rows[-1]
        T_f = row["T_fuel_K"]
        T_m = row["T_moderator_K"]
        rho_fb_solver = row["rho_feedback"]

        rho_out = ctypes.c_double(0.0)
        fortran_lib.compute_feedback(
            ctypes.c_double(T_f), ctypes.c_double(T_m),
            ctypes.c_double(T_F0), ctypes.c_double(T_M0),
            ctypes.c_double(ALPHA_F), ctypes.c_double(ALPHA_M),
            ctypes.byref(rho_out),
        )

        assert abs(rho_fb_solver - rho_out.value) < 1e-5, (
            f"Super-prompt feedback mismatch: "
            f"solver={rho_fb_solver:.8f}, Fortran={rho_out.value:.8f}"
        )


# ---- Step half-dollar tests ----


class TestStepHalfDollar:
    NAME = "step_half_dollar"

    def test_equilibrium_power(self):
        """Equilibrium power must match nonlinear spectral-corrected prediction."""
        rho_ext = 0.5 * BETA_TOTAL
        n_eq = _nonlinear_equilibrium(rho_ext)
        summary = load_summary()
        n_final = summary[self.NAME]["final_power_relative"]
        rel_err = abs(n_final - n_eq) / n_eq
        assert rel_err < 0.02, (
            f"Step 0.5$: final power {n_final:.4f} vs analytical {n_eq:.4f}, "
            f"relative error {rel_err:.4f}"
        )

    def test_power_increases(self):
        summary = load_summary()
        assert summary[self.NAME]["final_power_relative"] > 1.0

    def test_equilibrium_fuel_temperature(self):
        summary = load_summary()
        assert summary[self.NAME]["final_fuel_temp_K"] > T_F0

    def test_external_reactivity_is_constant(self):
        rows = load_csv(self.NAME)
        rho_expected = 0.5 * BETA_TOTAL
        for row in rows[1:]:
            assert abs(row["rho_external"] - rho_expected) < 1e-8, (
                f"External reactivity should be {rho_expected} "
                f"but got {row['rho_external']} at t={row['time_s']}"
            )

    def test_feedback_opposes_insertion(self):
        rows = load_csv(self.NAME)
        assert rows[-1]["rho_feedback"] < 0


# ---- Step super-prompt tests ----


class TestStepSuperPrompt:
    NAME = "step_super_prompt"

    def test_peak_power_high(self):
        summary = load_summary()
        peak = summary[self.NAME]["peak_power_relative"]
        assert peak > 15.0, f"Super-prompt peak power {peak:.1f} should be > 15"

    def test_peak_occurs_quickly(self):
        summary = load_summary()
        t_peak = summary[self.NAME]["time_of_peak_s"]
        assert t_peak < 0.2, f"Super-prompt peak at t={t_peak:.4f}s should be < 0.2s"

    def test_power_decreases_after_peak(self):
        summary = load_summary()
        peak = summary[self.NAME]["peak_power_relative"]
        final = summary[self.NAME]["final_power_relative"]
        assert final < peak * 0.5

    def test_fuel_temperature_rises(self):
        summary = load_summary()
        assert summary[self.NAME]["final_fuel_temp_K"] > T_F0 + 50


# ---- Ramp then hold tests ----


class TestRampThenHold:
    NAME = "ramp_then_hold"

    def test_power_increases_during_ramp(self):
        rows = load_csv(self.NAME)
        n_early = None
        n_mid = None
        for row in rows:
            if abs(row["time_s"] - 5.0) < 0.5:
                n_early = row["n_relative"]
            if abs(row["time_s"] - 25.0) < 0.5:
                n_mid = row["n_relative"]
        assert n_early is not None and n_mid is not None
        assert n_mid > n_early

    def test_final_power_above_unity(self):
        summary = load_summary()
        assert summary[self.NAME]["final_power_relative"] > 1.0

    def test_external_reactivity_holds_after_ramp(self):
        rows = load_csv(self.NAME)
        rho_hold = 10.0 * 30.0 * 1e-5  # 300 pcm
        for row in rows:
            if row["time_s"] > 35.0:
                assert abs(row["rho_external"] - rho_hold) < 1e-7

    def test_ramp_linearity(self):
        rows = load_csv(self.NAME)
        rate = 10.0 * 1e-5
        for row in rows:
            t = row["time_s"]
            if 1.0 < t < 29.0:
                rho_expected = rate * t
                assert abs(row["rho_external"] - rho_expected) < 1e-6


# ---- Oscillatory tests ----


class TestOscillatory:
    NAME = "oscillatory"

    def test_power_oscillates(self):
        rows = load_csv(self.NAME)
        n_vals = [r["n_relative"] for r in rows]
        maxima = 0
        minima = 0
        for i in range(1, len(n_vals) - 1):
            if n_vals[i] > n_vals[i - 1] and n_vals[i] > n_vals[i + 1]:
                maxima += 1
            if n_vals[i] < n_vals[i - 1] and n_vals[i] < n_vals[i + 1]:
                minima += 1
        assert maxima >= 5, f"Expected >= 5 power maxima, found {maxima}"
        assert minima >= 5, f"Expected >= 5 power minima, found {minima}"

    def test_power_bounded(self):
        rows = load_csv(self.NAME)
        n_vals = [r["n_relative"] for r in rows]
        assert max(n_vals) < 3.0
        assert min(n_vals) > 0.3

    def test_dominant_frequency(self):
        rows = load_csv(self.NAME)
        n_vals = np.array([r["n_relative"] for r in rows])
        times = np.array([r["time_s"] for r in rows])
        dt = np.median(np.diff(times))
        n_detrended = n_vals - np.mean(n_vals)
        fft_vals = np.abs(np.fft.rfft(n_detrended))
        freqs = np.fft.rfftfreq(len(n_detrended), d=dt)
        dominant_idx = np.argmax(fft_vals[1:]) + 1
        dominant_freq = freqs[dominant_idx]
        assert abs(dominant_freq - 0.1) < 0.02, (
            f"Dominant frequency {dominant_freq:.3f} Hz should be ~0.1 Hz"
        )

    def test_external_reactivity_sinusoidal(self):
        rows = load_csv(self.NAME)
        amplitude = 100.0 * 1e-5
        freq = 0.1
        for row in rows:
            t = row["time_s"]
            expected = amplitude * math.sin(2 * math.pi * freq * t)
            assert abs(row["rho_external"] - expected) < 1e-7


# ---- Scram tests ----


class TestScram:
    NAME = "scram"

    def test_power_drops(self):
        summary = load_summary()
        assert summary[self.NAME]["final_power_relative"] < 0.15

    def test_prompt_drop(self):
        rows = load_csv(self.NAME)
        rho_ext = -5000.0 * 1e-5
        prompt_factor = BETA_TOTAL / (BETA_TOTAL - rho_ext)
        n_after_prompt = None
        for row in rows:
            if 0.05 < row["time_s"] < 0.2:
                n_after_prompt = row["n_relative"]
                break
        assert n_after_prompt is not None
        assert n_after_prompt < prompt_factor * 2.0

    def test_power_generally_decreasing(self):
        rows = load_csv(self.NAME)
        powers = {}
        for row in rows:
            for t_check in [1.0, 10.0, 40.0]:
                if abs(row["time_s"] - t_check) < 0.5:
                    powers[t_check] = row["n_relative"]
        if 1.0 in powers and 10.0 in powers:
            assert powers[10.0] < powers[1.0] * 1.1
        if 10.0 in powers and 40.0 in powers:
            assert powers[40.0] < powers[10.0] * 1.1

    def test_fuel_temperature_drops(self):
        summary = load_summary()
        assert summary[self.NAME]["final_fuel_temp_K"] < T_F0 - 10

    def test_negative_external_reactivity(self):
        rows = load_csv(self.NAME)
        for row in rows[1:]:
            assert row["rho_external"] < -0.04


# ---- Rod calibration tests ----


class TestRodCalibration:
    NAME = "rod_calibration"

    def test_rod_worth_value(self):
        """Rod worth must match prompt-jump analytical value."""
        analysis = load_analysis()
        rw = analysis[self.NAME]["rod_worth_dk_k"]
        expected = _expected_rod_worth()
        rel_err = abs(rw - expected) / abs(expected)
        assert rel_err < 0.01, (
            f"Rod worth {rw:.6f} vs expected {expected:.6f}, "
            f"relative error {rel_err:.4f}"
        )

    def test_rod_worth_is_negative(self):
        analysis = load_analysis()
        assert analysis[self.NAME]["rod_worth_dk_k"] < 0

    def test_power_drops_promptly(self):
        """Power should drop to near the measured ratio after the step."""
        rows = load_csv(self.NAME)
        # First non-zero time point (dt ~ 0.05 s)
        n_after = rows[1]["n_relative"]
        assert n_after < 0.20, (
            f"Post-drop power {n_after:.4f} should be < 0.20"
        )
        assert n_after > 0.04, (
            f"Post-drop power {n_after:.4f} should be > 0.04"
        )

    def test_final_power_low(self):
        summary = load_summary()
        assert summary[self.NAME]["final_power_relative"] < 0.05

    def test_fuel_temperature_decreases(self):
        summary = load_summary()
        assert summary[self.NAME]["final_fuel_temp_K"] < T_F0 - 10

    def test_external_reactivity_constant_negative(self):
        """External reactivity should match computed rod worth."""
        rows = load_csv(self.NAME)
        expected_rw = _expected_rod_worth()
        for row in rows[1:]:
            assert abs(row["rho_external"] - expected_rw) < 1e-6, (
                f"Rod drop external reactivity {row['rho_external']:.6f} "
                f"should equal {expected_rw:.6f} at t={row['time_s']}"
            )

    def test_power_monotonically_decreasing(self):
        """After prompt drop, power should generally decrease."""
        rows = load_csv(self.NAME)
        powers = {}
        for row in rows:
            for t_check in [1.0, 10.0, 50.0]:
                if abs(row["time_s"] - t_check) < 0.5:
                    powers[t_check] = row["n_relative"]
        if 1.0 in powers and 10.0 in powers:
            assert powers[10.0] < powers[1.0] * 1.1
        if 10.0 in powers and 50.0 in powers:
            assert powers[50.0] < powers[10.0] * 1.1


# ---- Inhour equation analysis tests ----


class TestInhourAnalysis:
    def test_step_half_dollar_period(self):
        """Inhour period for sub-prompt-critical step."""
        analysis = load_analysis()
        period = analysis["step_half_dollar"]["inhour_period_s"]
        rho = 0.5 * BETA_TOTAL
        expected = _solve_inhour_period_ref(rho)
        rel_err = abs(period - expected) / expected
        assert rel_err < 0.05, (
            f"Inhour period {period:.4f} vs ref {expected:.4f}, "
            f"rel error {rel_err:.4f}"
        )

    def test_step_super_prompt_period(self):
        """Inhour period for super-prompt-critical step."""
        analysis = load_analysis()
        period = analysis["step_super_prompt"]["inhour_period_s"]
        rho = 1.5 * BETA_TOTAL
        expected = _solve_inhour_period_ref(rho)
        rel_err = abs(period - expected) / expected
        assert rel_err < 0.05, (
            f"Inhour period {period:.6f} vs ref {expected:.6f}, "
            f"rel error {rel_err:.4f}"
        )

    def test_super_prompt_period_much_shorter(self):
        """Super-prompt period must be orders of magnitude shorter."""
        analysis = load_analysis()
        T_half = analysis["step_half_dollar"]["inhour_period_s"]
        T_super = analysis["step_super_prompt"]["inhour_period_s"]
        assert T_super < T_half * 0.01, (
            f"Super-prompt period {T_super:.6f} should be << "
            f"sub-critical period {T_half:.4f}"
        )

    def test_inhour_period_positive(self):
        analysis = load_analysis()
        for name in ["step_half_dollar", "step_super_prompt"]:
            assert analysis[name]["inhour_period_s"] > 0

    def test_sub_critical_period_order_of_magnitude(self):
        """Sub-critical stable period should be on the order of seconds."""
        analysis = load_analysis()
        T = analysis["step_half_dollar"]["inhour_period_s"]
        assert 0.5 < T < 100.0, f"Sub-critical period {T:.4f} out of range"

    def test_super_prompt_period_order_of_magnitude(self):
        """Super-prompt period should be on the order of milliseconds."""
        analysis = load_analysis()
        T = analysis["step_super_prompt"]["inhour_period_s"]
        assert 1e-5 < T < 0.1, f"Super-prompt period {T:.6f} out of range"


# ---- Cross-scenario consistency tests ----


class TestCrossScenarioConsistency:
    def test_step_scenarios_ordering(self):
        summary = load_summary()
        peak_half = summary["step_half_dollar"]["peak_power_relative"]
        peak_super = summary["step_super_prompt"]["peak_power_relative"]
        assert peak_super > peak_half

    def test_scram_vs_step_temperatures(self):
        summary = load_summary()
        T_scram = summary["scram"]["final_fuel_temp_K"]
        T_step = summary["step_half_dollar"]["final_fuel_temp_K"]
        assert T_scram < T_step

    def test_rod_drop_vs_step_temperatures(self):
        """Rod drop should result in lower temperatures than positive insertion."""
        summary = load_summary()
        T_rod = summary["rod_calibration"]["final_fuel_temp_K"]
        T_step = summary["step_half_dollar"]["final_fuel_temp_K"]
        assert T_rod < T_step

    def test_negative_scenarios_final_power_below_unity(self):
        """Both scram and rod_calibration should end with power < 1."""
        summary = load_summary()
        assert summary["scram"]["final_power_relative"] < 1.0
        assert summary["rod_calibration"]["final_power_relative"] < 1.0
