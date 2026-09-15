
"""
Verification tests for the PC-SAFT equation of state implementation.

Reference values are from the FeOs library (https://github.com/feos-org/feos)
which implements the same PC-SAFT model with automatic differentiation.
"""

import json
import os
import pytest

RESULTS_PATH = "/app/results.json"

# Reference values from FeOs test suite
# (Gross & Sadowski 2001 parameters for propane)
REF_A_HS_X_V = 0.410610492598808
REF_A_HC_X_V = -0.12402626171926148
REF_A_DISP_X_V = -1.0622531100351962
REF_TC_KELVIN = 375.12441
REF_RHOC_MOL_M3 = 4733.00377


@pytest.fixture(scope="module")
def results():
    """Load the results.json produced by the Rust binary."""
    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}. "
        "Ensure 'cargo run --release' was executed in /app/."
    )
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    required_keys = [
        "a_hs_x_v", "a_hc_x_v", "a_disp_x_v",
        "tc_kelvin", "rhoc_mol_m3",
        "psat_ratio", "fugacity_diff",
    ]
    for key in required_keys:
        assert key in data, f"Missing key '{key}' in results.json"
    return data


class TestHelmholtzEnergy:
    """Verify individual Helmholtz energy contributions at the reference state
    (T=250 K, V=1000 A^3, N=1, propane)."""

    def test_hard_sphere(self, results):
        val = results["a_hs_x_v"]
        rel_err = abs(val - REF_A_HS_X_V) / abs(REF_A_HS_X_V)
        assert rel_err < 1e-4, (
            f"Hard sphere A*V = {val}, expected {REF_A_HS_X_V}, "
            f"relative error {rel_err:.2e}"
        )

    def test_hard_chain(self, results):
        val = results["a_hc_x_v"]
        rel_err = abs(val - REF_A_HC_X_V) / abs(REF_A_HC_X_V)
        assert rel_err < 1e-4, (
            f"Hard chain A*V = {val}, expected {REF_A_HC_X_V}, "
            f"relative error {rel_err:.2e}"
        )

    def test_dispersion(self, results):
        val = results["a_disp_x_v"]
        rel_err = abs(val - REF_A_DISP_X_V) / abs(REF_A_DISP_X_V)
        assert rel_err < 1e-4, (
            f"Dispersion A*V = {val}, expected {REF_A_DISP_X_V}, "
            f"relative error {rel_err:.2e}"
        )


class TestCriticalPoint:
    """Verify the critical point of propane."""

    def test_critical_temperature(self, results):
        tc = results["tc_kelvin"]
        err = abs(tc - REF_TC_KELVIN)
        assert err < 0.5, (
            f"Critical temperature = {tc:.4f} K, expected {REF_TC_KELVIN} K, "
            f"error {err:.4f} K (tolerance 0.5 K)"
        )

    def test_critical_density(self, results):
        rhoc = results["rhoc_mol_m3"]
        rel_err = abs(rhoc - REF_RHOC_MOL_M3) / REF_RHOC_MOL_M3
        assert rel_err < 0.01, (
            f"Critical density = {rhoc:.2f} mol/m^3, expected {REF_RHOC_MOL_M3} mol/m^3, "
            f"relative error {rel_err:.4f} (tolerance 1%)"
        )


class TestVLE:
    """Verify vapor-liquid equilibrium at T=300 K for propane."""

    def test_pressure_equality(self, results):
        ratio = results["psat_ratio"]
        err = abs(ratio - 1.0)
        assert err < 1e-4, (
            f"P_vapor/P_liquid = {ratio:.10f}, deviation from 1.0 = {err:.2e} "
            f"(tolerance 1e-4)"
        )

    def test_fugacity_equality(self, results):
        diff = results["fugacity_diff"]
        assert diff < 1e-3, (
            f"|mu_vapor - mu_liquid|/(kT) = {diff:.6e} "
            f"(tolerance 1e-3)"
        )
