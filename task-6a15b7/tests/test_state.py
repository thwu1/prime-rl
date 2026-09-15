"""Verification tests for porous media CFD V&V assessment.

Tests independently compute expected values from ground-truth simulation
parameters and compare against the agent's results.json and plot outputs.
"""

import json
import math
import os

import pytest

# ---- Ground truth simulation parameters ----
K_TRUE = 1.85e-10       # intrinsic permeability [m^2]
P_CONV = 2.12           # grid convergence order
BETA = 1.2e5            # Forchheimer coefficient [m^-1]
MU = 1.0e-3             # dynamic viscosity [Pa.s]
RHO = 1000.0            # density [kg/m^3]
L = 4.0e-3              # domain length [m]
D_P = 2.0e-4            # particle diameter [m]
POROSITY = 0.5567
MESH_DP = 0.50          # pressure drop for mesh study [Pa]
NX_VALUES = [100, 200, 400]

# Mesh error model (same as data generation)
_h_coarse = L / NX_VALUES[0]
_C_MESH = 0.05 * K_TRUE / (_h_coarse ** P_CONV)


def _expected_permeabilities():
    """Compute expected Darcy permeabilities for each mesh resolution."""
    perms = []
    for nx in NX_VALUES:
        h = L / nx
        k_app = K_TRUE + _C_MESH * (h ** P_CONV)
        perms.append(k_app)
    return perms


def _expected_richardson():
    """Compute expected Richardson extrapolation results."""
    ks = _expected_permeabilities()
    r = 2.0
    p_obs = math.log((ks[0] - ks[1]) / (ks[1] - ks[2])) / math.log(r)
    k_ext = ks[2] + (ks[2] - ks[1]) / (r ** p_obs - 1.0)
    eps_a = abs((ks[2] - ks[1]) / ks[2])
    gci_pct = 1.25 * eps_a / (r ** p_obs - 1.0) * 100.0
    return p_obs, k_ext, gci_pct


def _expected_asymptotic_ratio():
    """Compute expected asymptotic convergence ratio."""
    ks = _expected_permeabilities()
    r = 2.0
    p_obs = _expected_richardson()[0]
    # GCI for coarse pair (grids 0, 1)
    e_coarse = abs(ks[0] - ks[1]) / ks[1]
    gci_coarse = 1.25 * e_coarse / (r ** p_obs - 1.0)
    # GCI for fine pair (grids 1, 2)
    e_fine = abs(ks[1] - ks[2]) / ks[2]
    gci_fine = 1.25 * e_fine / (r ** p_obs - 1.0)
    return gci_coarse / (r ** p_obs * gci_fine)


def _expected_flow_regime():
    """Compute expected Forchheimer fit results."""
    a = MU / K_TRUE
    b = BETA * RHO
    k_darcy = MU / a
    beta_fit = b / RHO
    U_crit = a / (9.0 * b)
    Re_crit = RHO * U_crit * D_P / MU
    return k_darcy, beta_fit, Re_crit


def _expected_kozeny_carman():
    """Compute Kozeny-Carman permeability for the packing geometry."""
    return D_P ** 2 * POROSITY ** 3 / (180.0 * (1 - POROSITY) ** 2)


def _expected_validation_error():
    """Compute expected validation error percentage."""
    k_kc = _expected_kozeny_carman()
    return abs(K_TRUE - k_kc) / k_kc * 100.0


@pytest.fixture
def results():
    with open("/app/results.json") as f:
        return json.load(f)


# ==== Structure tests ====

class TestStructure:
    def test_top_level_keys(self, results):
        assert "verification" in results, "Missing key: verification"
        assert "validation" in results, "Missing key: validation"

    def test_verification_keys(self, results):
        v = results["verification"]
        for key in ["permeabilities", "convergence_order", "asymptotic_ratio",
                     "extrapolated_value", "discretization_uncertainty_pct",
                     "in_asymptotic_range"]:
            assert key in v, "Missing key: verification.{}".format(key)

    def test_validation_keys(self, results):
        v = results["validation"]
        for key in ["intrinsic_permeability", "inertial_coefficient",
                     "transition_reynolds", "kozeny_carman_permeability",
                     "validation_error_pct"]:
            assert key in v, "Missing key: validation.{}".format(key)

    def test_permeability_count(self, results):
        perms = results["verification"]["permeabilities"]
        assert isinstance(perms, list), "permeabilities must be a list"
        assert len(perms) == 3, (
            "Expected 3 permeability values, got {}".format(len(perms)))


# ==== Verification tests ====

class TestVerification:
    def test_permeability_values(self, results):
        expected = _expected_permeabilities()
        actual = results["verification"]["permeabilities"]
        for i, (exp, act) in enumerate(zip(expected, actual)):
            rel_err = abs(act - exp) / exp
            assert rel_err < 0.01, (
                "Permeability[{}]: expected {:.6e}, got {:.6e} "
                "(rel error {:.4%})".format(i, exp, act, rel_err))

    def test_permeability_ordering(self, results):
        perms = results["verification"]["permeabilities"]
        assert perms[0] > perms[1] > perms[2], (
            "Permeabilities should decrease with refinement: {}".format(perms))

    def test_convergence_order(self, results):
        p_exp, _, _ = _expected_richardson()
        p_act = results["verification"]["convergence_order"]
        assert abs(p_act - p_exp) < 0.1, (
            "Convergence order: expected {:.4f}, got {:.4f}".format(
                p_exp, p_act))

    def test_convergence_order_reasonable(self, results):
        p = results["verification"]["convergence_order"]
        assert 1.0 < p < 4.0, (
            "Convergence order {:.2f} outside [1, 4]".format(p))

    def test_extrapolated_value(self, results):
        _, k_ext_exp, _ = _expected_richardson()
        k_ext_act = results["verification"]["extrapolated_value"]
        rel_err = abs(k_ext_act - k_ext_exp) / k_ext_exp
        assert rel_err < 0.02, (
            "Extrapolated value: expected {:.6e}, got {:.6e} "
            "(rel error {:.4%})".format(k_ext_exp, k_ext_act, rel_err))

    def test_extrapolated_less_than_fine(self, results):
        v = results["verification"]
        k_ext = v["extrapolated_value"]
        k_fine = v["permeabilities"][2]
        assert k_ext < k_fine, (
            "Extrapolated ({:.6e}) should be < fine-grid ({:.6e})".format(
                k_ext, k_fine))

    def test_discretization_uncertainty(self, results):
        _, _, gci_exp = _expected_richardson()
        gci_act = results["verification"]["discretization_uncertainty_pct"]
        rel_err = abs(gci_act - gci_exp) / gci_exp
        assert rel_err < 0.15, (
            "Discretization uncertainty: expected {:.4f}%, got {:.4f}% "
            "(rel error {:.4%})".format(gci_exp, gci_act, rel_err))

    def test_discretization_uncertainty_positive(self, results):
        assert results["verification"]["discretization_uncertainty_pct"] > 0

    def test_asymptotic_ratio(self, results):
        ratio_exp = _expected_asymptotic_ratio()
        ratio_act = results["verification"]["asymptotic_ratio"]
        rel_err = abs(ratio_act - ratio_exp) / ratio_exp
        assert rel_err < 0.10, (
            "Asymptotic ratio: expected {:.6f}, got {:.6f} "
            "(rel error {:.4%})".format(ratio_exp, ratio_act, rel_err))

    def test_in_asymptotic_range(self, results):
        in_range = results["verification"]["in_asymptotic_range"]
        assert isinstance(in_range, bool), "in_asymptotic_range must be bool"
        ratio = results["verification"]["asymptotic_ratio"]
        expected_in_range = abs(ratio - 1.0) < 0.05
        assert in_range == expected_in_range, (
            "in_asymptotic_range: ratio={:.4f}, expected {}, got {}".format(
                ratio, expected_in_range, in_range))


# ==== Validation tests ====

class TestValidation:
    def test_intrinsic_permeability(self, results):
        k_exp, _, _ = _expected_flow_regime()
        k_act = results["validation"]["intrinsic_permeability"]
        rel_err = abs(k_act - k_exp) / k_exp
        assert rel_err < 0.02, (
            "Intrinsic permeability: expected {:.6e}, got {:.6e} "
            "(rel error {:.4%})".format(k_exp, k_act, rel_err))

    def test_intrinsic_permeability_positive(self, results):
        assert results["validation"]["intrinsic_permeability"] > 0

    def test_inertial_coefficient(self, results):
        _, beta_exp, _ = _expected_flow_regime()
        beta_act = results["validation"]["inertial_coefficient"]
        rel_err = abs(beta_act - beta_exp) / beta_exp
        assert rel_err < 0.05, (
            "Inertial coefficient: expected {:.4e}, got {:.4e} "
            "(rel error {:.4%})".format(beta_exp, beta_act, rel_err))

    def test_inertial_coefficient_positive(self, results):
        assert results["validation"]["inertial_coefficient"] > 0

    def test_transition_reynolds(self, results):
        _, _, Re_exp = _expected_flow_regime()
        Re_act = results["validation"]["transition_reynolds"]
        rel_err = abs(Re_act - Re_exp) / Re_exp
        assert rel_err < 0.10, (
            "Transition Re: expected {:.6f}, got {:.6f} "
            "(rel error {:.4%})".format(Re_exp, Re_act, rel_err))

    def test_transition_reynolds_reasonable(self, results):
        Re = results["validation"]["transition_reynolds"]
        assert 0.001 < Re < 100, (
            "Transition Re = {:.4f} outside [0.001, 100]".format(Re))

    def test_kozeny_carman(self, results):
        k_kc_exp = _expected_kozeny_carman()
        k_kc_act = results["validation"]["kozeny_carman_permeability"]
        rel_err = abs(k_kc_act - k_kc_exp) / k_kc_exp
        assert rel_err < 0.02, (
            "Kozeny-Carman: expected {:.6e}, got {:.6e} "
            "(rel error {:.4%})".format(k_kc_exp, k_kc_act, rel_err))

    def test_validation_error(self, results):
        val_err_exp = _expected_validation_error()
        val_err_act = results["validation"]["validation_error_pct"]
        assert abs(val_err_act - val_err_exp) < 0.20 * val_err_exp + 0.5, (
            "Validation error: expected {:.2f}%, got {:.2f}%".format(
                val_err_exp, val_err_act))

    def test_validation_error_positive(self, results):
        assert results["validation"]["validation_error_pct"] >= 0


# ==== Gnuplot output tests ====

class TestGnuplotOutputs:
    def test_convergence_png_exists(self):
        assert os.path.isfile("/app/convergence.png"), (
            "convergence.png not found")

    def test_convergence_png_valid(self):
        with open("/app/convergence.png", "rb") as f:
            header = f.read(8)
        assert header[:4] == b"\x89PNG", (
            "convergence.png is not a valid PNG file")

    def test_convergence_gp_exists(self):
        assert os.path.isfile("/app/convergence.gp"), (
            "convergence.gp gnuplot script not found")

    def test_convergence_gp_content(self):
        with open("/app/convergence.gp") as f:
            content = f.read().lower()
        assert "set terminal" in content or "set term" in content, (
            "convergence.gp missing terminal setting")
        assert "plot" in content, (
            "convergence.gp missing plot command")

    def test_regime_png_exists(self):
        assert os.path.isfile("/app/regime.png"), "regime.png not found"

    def test_regime_png_valid(self):
        with open("/app/regime.png", "rb") as f:
            header = f.read(8)
        assert header[:4] == b"\x89PNG", (
            "regime.png is not a valid PNG file")

    def test_regime_gp_exists(self):
        assert os.path.isfile("/app/regime.gp"), (
            "regime.gp gnuplot script not found")

    def test_regime_gp_content(self):
        with open("/app/regime.gp") as f:
            content = f.read().lower()
        assert "set terminal" in content or "set term" in content, (
            "regime.gp missing terminal setting")
        assert "plot" in content, (
            "regime.gp missing plot command")
