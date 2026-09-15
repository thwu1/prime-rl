#!/usr/bin/env python3
"""Tests for phased array beamforming pipeline."""

import json
import math
import os
import subprocess
import sys

import numpy as np
import pytest
from scipy.signal.windows import chebwin

sys.path.insert(0, "/app")
from lib.formats import read_s1p, read_coupling_matrix


# ---------------------------------------------------------------------------
# Helper functions for independent verification
# ---------------------------------------------------------------------------

def compute_af(weights, d_lambda, theta, scan_rad):
    """Array factor (independent computation)."""
    kd = 2 * np.pi * d_lambda
    psi = kd * (np.cos(theta) - np.cos(scan_rad))
    af = np.zeros_like(theta, dtype=complex)
    for n in range(len(weights)):
        af += weights[n] * np.exp(1j * n * psi)
    return af


def compute_directivity(weights, d_lambda, scan_rad, n_pts=20001):
    """Directivity in dBi (independent computation)."""
    theta = np.linspace(1e-7, np.pi - 1e-7, n_pts)
    af = compute_af(weights, d_lambda, theta, scan_rad)
    af_sq = np.abs(af) ** 2
    U_max = np.max(af_sq)
    integrand = af_sq * np.sin(theta)
    integral = np.trapezoid(integrand, theta)
    D = 2.0 * U_max / integral
    return 10.0 * np.log10(D)


def s11_to_impedance(s_data, freq):
    """Convert S-parameter data to impedance at given frequency."""
    z0 = s_data["z0"]
    freqs = np.array(s_data["frequencies"])
    s11_r = np.array([s.real for s in s_data["s11"]])
    s11_i = np.array([s.imag for s in s_data["s11"]])
    sr = float(np.interp(freq, freqs, s11_r))
    si = float(np.interp(freq, freqs, s11_i))
    s11 = complex(sr, si)
    return z0 * (1 + s11) / (1 - s11)


def impedance_transform(z_load, z0, length_wl):
    """Transmission line impedance transformation (wavelengths)."""
    beta_l = 2.0 * math.pi * length_wl
    tan_bl = math.tan(beta_l)
    return z0 * (z_load + 1j * z0 * tan_bl) / (z0 + 1j * z_load * tan_bl)


def gamma_mag(z_in, z0):
    return abs((z_in - z0) / (z_in + z0))


def compute_vswr(g):
    if g >= 1.0:
        return float("inf")
    return (1 + g) / (1 - g)


def compute_mismatch_loss(g):
    if g >= 1.0:
        return float("inf")
    return -10 * math.log10(1 - g ** 2)


C_LIGHT = 299792458.0


def compute_fspl(freq_hz, dist_m):
    return 20 * math.log10(4 * math.pi * dist_m * freq_hz / C_LIGHT)


# ---------------------------------------------------------------------------
# Load scenario + output helpers
# ---------------------------------------------------------------------------

def load_scenario(name):
    path = "/app/scenarios/{}.json".format(name)
    with open(path) as f:
        return json.load(f)


def load_output(name):
    path = "/app/output/{}.json".format(name)
    with open(path) as f:
        return json.load(f)


def run_pipeline():
    """Run pipeline --run-all and return result."""
    result = subprocess.run(
        ["python3", "/app/pipeline.py", "--run-all"],
        capture_output=True, text=True, timeout=120,
    )
    return result


def run_pipeline_single(scenario_path):
    """Run pipeline on a single scenario file."""
    result = subprocess.run(
        ["python3", "/app/pipeline.py", scenario_path],
        capture_output=True, text=True, timeout=120,
    )
    return result


# ---------------------------------------------------------------------------
# Run pipeline once for all tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def pipeline_run():
    result = run_pipeline()
    assert result.returncode == 0, (
        "Pipeline --run-all failed:\nstdout:\n{}\nstderr:\n{}".format(
            result.stdout, result.stderr)
    )


# ===========================================================================
# Pipeline execution tests
# ===========================================================================

class TestPipelineExecution:

    def test_output_files_exist(self):
        for name in ["scenario_01", "scenario_02", "scenario_03"]:
            assert os.path.exists("/app/output/{}.json".format(name)), (
                "Missing output for {}".format(name))

    def test_output_schema_complete(self):
        required = [
            "ideal_weights", "coupled_weights",
            "array_directivity_dBi", "coupled_directivity_dBi",
            "tx_element_impedance_ohms", "tx_input_impedance_ohms",
            "tx_reflection_coefficient_mag", "tx_vswr", "tx_mismatch_loss_dB",
            "rx_input_impedance_ohms", "rx_reflection_coefficient_mag",
            "rx_vswr", "rx_mismatch_loss_dB",
            "free_space_path_loss_dB", "received_power_dBm",
        ]
        for name in ["scenario_01", "scenario_02", "scenario_03"]:
            out = load_output(name)
            for field in required:
                assert field in out, "Missing field {} in {}".format(field, name)


# ===========================================================================
# Dolph-Chebyshev weight tests
# ===========================================================================

class TestIdealWeights:

    @pytest.mark.parametrize("name,N,at", [
        ("scenario_01", 8, 25),
        ("scenario_02", 10, 20),
        ("scenario_03", 6, 30),
    ])
    def test_weights_match_chebwin(self, name, N, at):
        out = load_output(name)
        w = np.array(out["ideal_weights"])
        expected = chebwin(N, at)
        expected = expected / np.max(expected)
        np.testing.assert_allclose(w, expected, atol=0.005,
                                   err_msg="ideal_weights for {}".format(name))

    @pytest.mark.parametrize("name,N", [
        ("scenario_01", 8),
        ("scenario_02", 10),
        ("scenario_03", 6),
    ])
    def test_weights_symmetric(self, name, N):
        out = load_output(name)
        w = out["ideal_weights"]
        assert len(w) == N
        for i in range(N // 2):
            assert abs(w[i] - w[N - 1 - i]) < 0.005, (
                "Asymmetric: w[{}]={} != w[{}]={}".format(
                    i, w[i], N - 1 - i, w[N - 1 - i]))

    @pytest.mark.parametrize("name", ["scenario_01", "scenario_02", "scenario_03"])
    def test_weights_normalized(self, name):
        out = load_output(name)
        assert abs(max(out["ideal_weights"]) - 1.0) < 0.001


# ===========================================================================
# Coupling correction tests
# ===========================================================================

class TestCouplingCorrection:

    @pytest.mark.parametrize("name,N,at", [
        ("scenario_01", 8, 25),
        ("scenario_02", 10, 20),
        ("scenario_03", 6, 30),
    ])
    def test_coupled_weights_correct(self, name, N, at):
        out = load_output(name)
        w_coupled = np.array(out["coupled_weights"])

        # Independently compute
        w_ideal = chebwin(N, at)
        w_ideal = w_ideal / np.max(w_ideal)
        C = np.array(
            read_coupling_matrix("/app/data/coupling_{}.csv".format(N)),
            dtype=complex,
        )
        w_complex = np.linalg.solve(C, w_ideal)
        w_mags = np.abs(w_complex)
        expected = w_mags / np.max(w_mags)

        np.testing.assert_allclose(w_coupled, expected, atol=0.01,
                                   err_msg="coupled_weights for {}".format(name))

    @pytest.mark.parametrize("name", ["scenario_01", "scenario_02", "scenario_03"])
    def test_coupled_weights_differ_from_ideal(self, name):
        out = load_output(name)
        w_ideal = np.array(out["ideal_weights"])
        w_coupled = np.array(out["coupled_weights"])
        assert not np.allclose(w_ideal, w_coupled, atol=0.001), (
            "Coupled weights should differ from ideal for {}".format(name))


# ===========================================================================
# Directivity tests
# ===========================================================================

class TestDirectivity:

    @pytest.mark.parametrize("name,N,at,scan_deg", [
        ("scenario_01", 8, 25, 90),
        ("scenario_02", 10, 20, 60),
        ("scenario_03", 6, 30, 90),
    ])
    def test_array_directivity(self, name, N, at, scan_deg):
        out = load_output(name)
        w_ideal = chebwin(N, at)
        w_ideal = w_ideal / np.max(w_ideal)
        expected = compute_directivity(w_ideal, 0.5, np.radians(scan_deg))
        assert abs(out["array_directivity_dBi"] - expected) < 0.2, (
            "{}: {} vs {}".format(name, out["array_directivity_dBi"], expected))

    @pytest.mark.parametrize("name,N,at,scan_deg", [
        ("scenario_01", 8, 25, 90),
        ("scenario_02", 10, 20, 60),
        ("scenario_03", 6, 30, 90),
    ])
    def test_coupled_directivity(self, name, N, at, scan_deg):
        out = load_output(name)
        w_ideal = chebwin(N, at)
        w_ideal = w_ideal / np.max(w_ideal)
        C = np.array(
            read_coupling_matrix("/app/data/coupling_{}.csv".format(N)),
            dtype=complex,
        )
        w_complex = np.linalg.solve(C, w_ideal)
        expected = compute_directivity(w_complex, 0.5, np.radians(scan_deg))
        assert abs(out["coupled_directivity_dBi"] - expected) < 0.3, (
            "{}: {} vs {}".format(name, out["coupled_directivity_dBi"], expected))

    @pytest.mark.parametrize("name", ["scenario_01", "scenario_02", "scenario_03"])
    def test_directivity_sane_range(self, name):
        out = load_output(name)
        D = out["array_directivity_dBi"]
        assert 3.0 < D < 20.0, "Directivity {} dBi out of range".format(D)
        Dc = out["coupled_directivity_dBi"]
        assert 3.0 < Dc < 20.0, "Coupled directivity {} dBi out of range".format(Dc)


# ===========================================================================
# TX element impedance tests (S-parameter extraction)
# ===========================================================================

class TestElementImpedance:

    @pytest.mark.parametrize("name,freq,z_real,z_imag", [
        ("scenario_01", 2.4e9, 73.0, 42.5),
        ("scenario_02", 1.8e9, 65.0, 10.0),
        ("scenario_03", 5.8e9, 250.0, 300.0),
    ])
    def test_tx_element_impedance(self, name, freq, z_real, z_imag):
        out = load_output(name)
        z = out["tx_element_impedance_ohms"]
        assert abs(z[0] - z_real) < 1.0, (
            "{}: real {} vs {}".format(name, z[0], z_real))
        assert abs(z[1] - z_imag) < 1.0, (
            "{}: imag {} vs {}".format(name, z[1], z_imag))

    def test_s11_to_impedance_consistency(self):
        """Verify S-parameter to impedance conversion is correct."""
        s_data = read_s1p("/app/data/dipole_element.s1p")
        out = load_output("scenario_01")
        z_expected = s11_to_impedance(s_data, 2.4e9)
        assert abs(out["tx_element_impedance_ohms"][0] - z_expected.real) < 0.5
        assert abs(out["tx_element_impedance_ohms"][1] - z_expected.imag) < 0.5


# ===========================================================================
# Impedance matching tests
# ===========================================================================

class TestImpedanceMatching:

    def test_scenario_01_tx_impedance(self):
        """TX: complex load through 0.375-wavelength 50-ohm line."""
        out = load_output("scenario_01")
        z_load = complex(73.0, 42.5)
        z_in = impedance_transform(z_load, 50.0, 0.375)
        assert abs(out["tx_input_impedance_ohms"][0] - z_in.real) < 0.5
        assert abs(out["tx_input_impedance_ohms"][1] - z_in.imag) < 0.5

    def test_scenario_02_rx_half_wave(self):
        """RX: half-wave line passes through the load impedance."""
        out = load_output("scenario_02")
        # Half-wave line: Z_in = Z_L
        assert abs(out["rx_input_impedance_ohms"][0] - 75.0) < 0.5
        assert abs(out["rx_input_impedance_ohms"][1] - 0.0) < 0.5
        assert out["rx_reflection_coefficient_mag"] < 0.01
        assert abs(out["rx_vswr"] - 1.0) < 0.05

    def test_scenario_03_tx_half_wave(self):
        """TX: half-wave line passes through the load impedance."""
        out = load_output("scenario_03")
        # Half-wave line: Z_in = Z_L
        assert abs(out["tx_input_impedance_ohms"][0] - 250.0) < 2.0
        assert abs(out["tx_input_impedance_ohms"][1] - 300.0) < 2.0

    def test_scenario_01_rx_quarter_wave(self):
        """RX: quarter-wave transformer with complex load."""
        out = load_output("scenario_01")
        z_load = complex(36.5, -20.0)
        z_in = impedance_transform(z_load, 50.0, 0.25)
        assert abs(out["rx_input_impedance_ohms"][0] - z_in.real) < 0.5
        assert abs(out["rx_input_impedance_ohms"][1] - z_in.imag) < 0.5

    def test_vswr_and_gamma_consistency(self):
        """VSWR must equal (1+|Gamma|)/(1-|Gamma|)."""
        for name in ["scenario_01", "scenario_02", "scenario_03"]:
            out = load_output(name)
            for side in ["tx", "rx"]:
                g = out["{}_reflection_coefficient_mag".format(side)]
                v = out["{}_vswr".format(side)]
                if g < 0.999:
                    expected_v = (1 + g) / (1 - g)
                    assert abs(v - expected_v) < 0.05, (
                        "{} {}: VSWR {} vs {}".format(name, side, v, expected_v))

    def test_mismatch_loss_nonnegative(self):
        for name in ["scenario_01", "scenario_02", "scenario_03"]:
            out = load_output(name)
            assert out["tx_mismatch_loss_dB"] >= -0.001
            assert out["rx_mismatch_loss_dB"] >= -0.001


# ===========================================================================
# Link budget tests
# ===========================================================================

class TestLinkBudget:

    @pytest.mark.parametrize("name,freq,dist", [
        ("scenario_01", 2.4e9, 1000.0),
        ("scenario_02", 1.8e9, 2000.0),
        ("scenario_03", 5.8e9, 500.0),
    ])
    def test_fspl(self, name, freq, dist):
        out = load_output(name)
        expected = compute_fspl(freq, dist)
        assert abs(out["free_space_path_loss_dB"] - expected) < 0.01, (
            "{}: {} vs {}".format(name, out["free_space_path_loss_dB"], expected))

    @pytest.mark.parametrize("name,Pt_W,Gr", [
        ("scenario_01", 0.1, 6.0),
        ("scenario_02", 0.5, 3.0),
        ("scenario_03", 0.01, 10.0),
    ])
    def test_link_budget_consistency(self, name, Pt_W, Gr):
        """Prx = Pt_dBm + Gt + Gr - FSPL - ML_tx - ML_rx."""
        out = load_output(name)
        Pt_dBm = 10 * math.log10(Pt_W * 1000)
        expected = (Pt_dBm
                    + out["coupled_directivity_dBi"]
                    + Gr
                    - out["free_space_path_loss_dB"]
                    - out["tx_mismatch_loss_dB"]
                    - out["rx_mismatch_loss_dB"])
        assert abs(out["received_power_dBm"] - expected) < 0.5, (
            "{}: {} vs {}".format(name, out["received_power_dBm"], expected))


# ===========================================================================
# Anti-cheat: novel scenario not in /app/scenarios/
# ===========================================================================

class TestAntiCheat:

    def test_novel_scenario(self, tmp_path):
        """Test with a scenario whose parameters differ from all shipped ones."""
        novel = {
            "array": {
                "num_elements": 8,
                "element_spacing_wavelengths": 0.5,
                "sidelobe_level_dB": -22,
                "scan_angle_degrees": 75,
            },
            "element_data_file": "dipole_element.s1p",
            "frequency_hz": 3.0e9,
            "tx_power_watts": 0.2,
            "tx_line_z0_ohms": 50.0,
            "tx_line_length_wavelengths": 0.25,
            "rx_gain_dBi": 5.0,
            "rx_load_impedance_ohms": [50.0, 25.0],
            "rx_line_z0_ohms": 50.0,
            "rx_line_length_wavelengths": 0.375,
            "link_distance_meters": 800.0,
        }

        novel_path = str(tmp_path / "novel_ac.json")
        with open(novel_path, "w") as f:
            json.dump(novel, f)

        result = run_pipeline_single(novel_path)
        assert result.returncode == 0, (
            "Pipeline failed on novel scenario:\n{}".format(result.stderr))

        with open("/app/output/novel_ac.json") as f:
            out = json.load(f)

        # --- independently compute expected values ---
        N, at = 8, 22
        scan_rad = np.radians(75)

        # Ideal weights
        w_ideal = chebwin(N, at)
        w_ideal = w_ideal / np.max(w_ideal)
        np.testing.assert_allclose(
            out["ideal_weights"], w_ideal, atol=0.005,
            err_msg="novel: ideal_weights")

        # Coupling correction
        C = np.array(read_coupling_matrix("/app/data/coupling_8.csv"),
                     dtype=complex)
        w_complex = np.linalg.solve(C, w_ideal)
        w_mags = np.abs(w_complex) / np.max(np.abs(w_complex))
        np.testing.assert_allclose(
            out["coupled_weights"], w_mags, atol=0.01,
            err_msg="novel: coupled_weights")

        # Directivity
        exp_dir = compute_directivity(w_ideal, 0.5, scan_rad)
        assert abs(out["array_directivity_dBi"] - exp_dir) < 0.2

        exp_cdir = compute_directivity(w_complex, 0.5, scan_rad)
        assert abs(out["coupled_directivity_dBi"] - exp_cdir) < 0.3

        # TX element impedance at 3.0 GHz
        s_data = read_s1p("/app/data/dipole_element.s1p")
        z_elem = s11_to_impedance(s_data, 3.0e9)
        assert abs(out["tx_element_impedance_ohms"][0] - z_elem.real) < 1.0
        assert abs(out["tx_element_impedance_ohms"][1] - z_elem.imag) < 1.0

        # TX impedance matching (quarter-wave)
        tx_zin = impedance_transform(z_elem, 50.0, 0.25)
        assert abs(out["tx_input_impedance_ohms"][0] - tx_zin.real) < 0.5
        assert abs(out["tx_input_impedance_ohms"][1] - tx_zin.imag) < 0.5

        # RX impedance matching
        rx_zin = impedance_transform(complex(50, 25), 50.0, 0.375)
        assert abs(out["rx_input_impedance_ohms"][0] - rx_zin.real) < 0.5
        assert abs(out["rx_input_impedance_ohms"][1] - rx_zin.imag) < 0.5

        # FSPL
        exp_fspl = compute_fspl(3.0e9, 800.0)
        assert abs(out["free_space_path_loss_dB"] - exp_fspl) < 0.01

        # Link budget consistency
        Pt_dBm = 10 * math.log10(200)
        g_tx = gamma_mag(tx_zin, 50.0)
        g_rx = gamma_mag(rx_zin, 50.0)
        ml_tx = compute_mismatch_loss(g_tx)
        ml_rx = compute_mismatch_loss(g_rx)
        exp_prx = Pt_dBm + exp_cdir + 5.0 - exp_fspl - ml_tx - ml_rx
        assert abs(out["received_power_dBm"] - exp_prx) < 0.5

    def test_interpolation_scenario(self, tmp_path):
        """Test with a frequency not exactly in the S1P data (requires interpolation)."""
        novel = {
            "array": {
                "num_elements": 8,
                "element_spacing_wavelengths": 0.5,
                "sidelobe_level_dB": -28,
                "scan_angle_degrees": 90,
            },
            "element_data_file": "dipole_element.s1p",
            "frequency_hz": 2.2e9,
            "tx_power_watts": 0.05,
            "tx_line_z0_ohms": 75.0,
            "tx_line_length_wavelengths": 0.5,
            "rx_gain_dBi": 8.0,
            "rx_load_impedance_ohms": [100.0, 0.0],
            "rx_line_z0_ohms": 50.0,
            "rx_line_length_wavelengths": 0.25,
            "link_distance_meters": 1500.0,
        }

        novel_path = str(tmp_path / "novel_interp.json")
        with open(novel_path, "w") as f:
            json.dump(novel, f)

        result = run_pipeline_single(novel_path)
        assert result.returncode == 0, (
            "Pipeline failed on interpolation scenario:\n{}".format(result.stderr))

        with open("/app/output/novel_interp.json") as f:
            out = json.load(f)

        # TX element impedance at 2.2 GHz (interpolated between 2.0 and 2.4)
        s_data = read_s1p("/app/data/dipole_element.s1p")
        z_elem = s11_to_impedance(s_data, 2.2e9)
        assert abs(out["tx_element_impedance_ohms"][0] - z_elem.real) < 1.0, (
            "Interpolated Z real: {} vs {}".format(
                out["tx_element_impedance_ohms"][0], z_elem.real))
        assert abs(out["tx_element_impedance_ohms"][1] - z_elem.imag) < 1.0, (
            "Interpolated Z imag: {} vs {}".format(
                out["tx_element_impedance_ohms"][1], z_elem.imag))

        # Half-wave TX line: Z_in = Z_L (passthrough)
        assert abs(out["tx_input_impedance_ohms"][0] - z_elem.real) < 1.0
        assert abs(out["tx_input_impedance_ohms"][1] - z_elem.imag) < 1.0

        # RX: quarter-wave with 100+j0 load, Z0=50
        # Z_in = Z0^2/ZL = 2500/100 = 25
        assert abs(out["rx_input_impedance_ohms"][0] - 25.0) < 0.5
        assert abs(out["rx_input_impedance_ohms"][1]) < 0.5

        # Weights
        w_ideal = chebwin(8, 28)
        w_ideal = w_ideal / np.max(w_ideal)
        np.testing.assert_allclose(out["ideal_weights"], w_ideal, atol=0.005)

        # FSPL
        exp_fspl = compute_fspl(2.2e9, 1500.0)
        assert abs(out["free_space_path_loss_dB"] - exp_fspl) < 0.01

        # Link budget consistency
        Pt_dBm = 10 * math.log10(50)
        exp_prx = (Pt_dBm
                   + out["coupled_directivity_dBi"]
                   + 8.0
                   - out["free_space_path_loss_dB"]
                   - out["tx_mismatch_loss_dB"]
                   - out["rx_mismatch_loss_dB"])
        assert abs(out["received_power_dBm"] - exp_prx) < 0.5
