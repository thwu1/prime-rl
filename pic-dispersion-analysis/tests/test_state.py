"""
Tests for WarpX Simulation Configuration Audit.

Independently computes all expected values from hard-coded simulation
parameters and compares against the agent's audit_report.json output.

"""

import json
import os

import numpy as np
import pytest
from scipy import constants


# ---------------------------------------------------------------------------
# Hard-coded simulation parameters (from the static WarpX input files)
# ---------------------------------------------------------------------------

SIM_PARAMS = {
    "lpa_fine": {
        "n_cell": [64, 64, 768],
        "prob_lo": [-32e-6, -32e-6, -56e-6],
        "prob_hi": [32e-6, 32e-6, 12e-6],
        "cfl": 0.999,
        "n_e": 1.75e24,
        "laser_wl": 0.8e-6,
        "e_max": 16e12,
        "waist": 15e-6,
    },
    "lpa_coarse": {
        "n_cell": [16, 16, 120],
        "prob_lo": [-48e-6, -48e-6, -56e-6],
        "prob_hi": [48e-6, 48e-6, 12e-6],
        "cfl": 0.95,
        "n_e": 1.75e24,
        "laser_wl": 0.8e-6,
        "e_max": 16e12,
        "waist": 15e-6,
    },
    "lpa_dense": {
        "n_cell": [128, 128, 960],
        "prob_lo": [-24e-6, -24e-6, -56e-6],
        "prob_hi": [24e-6, 24e-6, 12e-6],
        "cfl": 0.999,
        "n_e": 7.0e24,
        "laser_wl": 0.8e-6,
        "e_max": 32e12,
        "waist": 10e-6,
    },
}

SIM_NAMES = list(SIM_PARAMS.keys())


# ---------------------------------------------------------------------------
# Reference computation (independent of the agent's code)
# ---------------------------------------------------------------------------

def _compute_expected(params):
    """Compute all expected values from first principles."""
    c = constants.c
    e = constants.e
    m_e = constants.m_e
    eps0 = constants.epsilon_0

    nx, ny, nz = params["n_cell"]
    xlo, ylo, zlo = params["prob_lo"]
    xhi, yhi, zhi = params["prob_hi"]
    cfl = params["cfl"]
    n_e = params["n_e"]
    lam = params["laser_wl"]
    E0 = params["e_max"]
    w0 = params["waist"]

    # Grid
    dx = (xhi - xlo) / nx
    dy = (yhi - ylo) / ny
    dz = (zhi - zlo) / nz
    total_cells = int(nx * ny * nz)

    # Timestep (3D Yee FDTD CFL)
    dt = cfl / (c * np.sqrt(1.0 / dx**2 + 1.0 / dy**2 + 1.0 / dz**2))

    # Laser
    omega_0 = 2.0 * np.pi * c / lam
    k_0 = 2.0 * np.pi / lam
    a_0 = e * E0 / (m_e * c * omega_0)
    I_peak_Wcm2 = c * eps0 * E0**2 / 2.0 * 1.0e-4
    z_R = np.pi * w0**2 / lam

    # Plasma
    omega_p = np.sqrt(n_e * e**2 / (eps0 * m_e))
    lambda_p = 2.0 * np.pi * c / omega_p
    skin_depth = c / omega_p
    n_c = eps0 * m_e * omega_0**2 / e**2
    density_ratio = n_e / n_c
    E_wb = m_e * c * omega_p / e

    # Resolution
    cells_per_laser_wl = lam / dz
    cells_per_skin_depth = skin_depth / min(dx, dy)
    cells_per_plasma_wl = lambda_p / dz

    # Numerical dispersion (Yee FDTD, wave along z, kx=ky=0)
    S = (c * dt / dz) * np.sin(k_0 * dz / 2.0)
    omega_num = (2.0 / dt) * np.arcsin(S)
    v_phi = omega_num / k_0
    v_g = c * np.cos(k_0 * dz / 2.0) / np.cos(omega_num * dt / 2.0)
    phase_err = (v_phi / c - 1.0) * 100.0
    group_err = (v_g / c - 1.0) * 100.0

    # Verdict
    cfl_stable = cfl <= 1.0
    well_resolved = (cells_per_laser_wl >= 8.0) and (cells_per_skin_depth >= 1.0)

    return {
        "grid": {
            "dx_m": dx, "dy_m": dy, "dz_m": dz,
            "total_cells": total_cells,
        },
        "timestep": {"dt_s": dt, "cfl_factor": cfl},
        "laser": {
            "wavelength_m": lam, "frequency_rad_s": omega_0,
            "wavenumber_1m": k_0, "peak_field_Vm": E0,
            "normalized_amplitude": a_0,
            "peak_intensity_Wcm2": I_peak_Wcm2,
            "rayleigh_length_m": z_R,
        },
        "plasma": {
            "density_m3": n_e, "frequency_rad_s": omega_p,
            "wavelength_m": lambda_p, "skin_depth_m": skin_depth,
            "critical_density_m3": n_c, "density_ratio": density_ratio,
            "wavebreaking_field_Vm": E_wb,
        },
        "resolution": {
            "cells_per_laser_wavelength": cells_per_laser_wl,
            "cells_per_skin_depth": cells_per_skin_depth,
            "cells_per_plasma_wavelength": cells_per_plasma_wl,
        },
        "numerical_dispersion": {
            "phase_error_pct": phase_err,
            "group_error_pct": group_err,
        },
        "verdict": {
            "cfl_stable": cfl_stable,
            "well_resolved": well_resolved,
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def report():
    path = "/app/audit_report.json"
    assert os.path.isfile(path), (
        f"Output file {path} not found. "
        "The agent must produce /app/audit_report.json."
    )
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def expected():
    return {name: _compute_expected(p) for name, p in SIM_PARAMS.items()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_close(actual, expected_val, rtol=1e-6, label=""):
    """Assert relative tolerance, with fallback to absolute for near-zero."""
    if expected_val == 0:
        assert abs(actual) < 1e-30, f"{label}: expected ~0, got {actual}"
    else:
        rel_err = abs(actual - expected_val) / abs(expected_val)
        assert rel_err < rtol, (
            f"{label}: relative error {rel_err:.2e} exceeds {rtol:.0e}. "
            f"actual={actual}, expected={expected_val}"
        )


# ---------------------------------------------------------------------------
# Tests: Report structure
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_file_exists(self):
        assert os.path.isfile("/app/audit_report.json")

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_simulation_present(self, report, sim):
        assert sim in report, f"Missing simulation '{sim}' in report"

    @pytest.mark.parametrize("sim", SIM_NAMES)
    @pytest.mark.parametrize("section", [
        "grid", "timestep", "laser", "plasma",
        "resolution", "numerical_dispersion", "verdict",
    ])
    def test_section_present(self, report, sim, section):
        assert section in report[sim], (
            f"Missing section '{section}' in report['{sim}']"
        )


# ---------------------------------------------------------------------------
# Tests: Grid parameters
# ---------------------------------------------------------------------------

class TestGridParameters:
    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_cell_sizes(self, report, expected, sim):
        for key in ["dx_m", "dy_m", "dz_m"]:
            _assert_close(
                report[sim]["grid"][key],
                expected[sim]["grid"][key],
                rtol=1e-6, label=f"{sim}.grid.{key}",
            )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_total_cells(self, report, expected, sim):
        assert report[sim]["grid"]["total_cells"] == expected[sim]["grid"]["total_cells"], (
            f"{sim}.grid.total_cells: got {report[sim]['grid']['total_cells']}, "
            f"expected {expected[sim]['grid']['total_cells']}"
        )


# ---------------------------------------------------------------------------
# Tests: Timestep
# ---------------------------------------------------------------------------

class TestTimestep:
    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_dt(self, report, expected, sim):
        _assert_close(
            report[sim]["timestep"]["dt_s"],
            expected[sim]["timestep"]["dt_s"],
            rtol=1e-6, label=f"{sim}.timestep.dt_s",
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_cfl_factor(self, report, expected, sim):
        _assert_close(
            report[sim]["timestep"]["cfl_factor"],
            expected[sim]["timestep"]["cfl_factor"],
            rtol=1e-9, label=f"{sim}.timestep.cfl_factor",
        )


# ---------------------------------------------------------------------------
# Tests: Laser parameters
# ---------------------------------------------------------------------------

class TestLaserParameters:
    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_wavelength(self, report, expected, sim):
        _assert_close(
            report[sim]["laser"]["wavelength_m"],
            expected[sim]["laser"]["wavelength_m"],
            rtol=1e-6, label=f"{sim}.laser.wavelength_m",
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_frequency(self, report, expected, sim):
        _assert_close(
            report[sim]["laser"]["frequency_rad_s"],
            expected[sim]["laser"]["frequency_rad_s"],
            rtol=1e-6, label=f"{sim}.laser.frequency_rad_s",
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_wavenumber(self, report, expected, sim):
        _assert_close(
            report[sim]["laser"]["wavenumber_1m"],
            expected[sim]["laser"]["wavenumber_1m"],
            rtol=1e-6, label=f"{sim}.laser.wavenumber_1m",
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_normalized_amplitude(self, report, expected, sim):
        _assert_close(
            report[sim]["laser"]["normalized_amplitude"],
            expected[sim]["laser"]["normalized_amplitude"],
            rtol=1e-6, label=f"{sim}.laser.normalized_amplitude",
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_peak_intensity(self, report, expected, sim):
        _assert_close(
            report[sim]["laser"]["peak_intensity_Wcm2"],
            expected[sim]["laser"]["peak_intensity_Wcm2"],
            rtol=1e-6, label=f"{sim}.laser.peak_intensity_Wcm2",
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_rayleigh_length(self, report, expected, sim):
        _assert_close(
            report[sim]["laser"]["rayleigh_length_m"],
            expected[sim]["laser"]["rayleigh_length_m"],
            rtol=1e-6, label=f"{sim}.laser.rayleigh_length_m",
        )


# ---------------------------------------------------------------------------
# Tests: Plasma parameters
# ---------------------------------------------------------------------------

class TestPlasmaParameters:
    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_density(self, report, expected, sim):
        _assert_close(
            report[sim]["plasma"]["density_m3"],
            expected[sim]["plasma"]["density_m3"],
            rtol=1e-6, label=f"{sim}.plasma.density_m3",
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_frequency(self, report, expected, sim):
        _assert_close(
            report[sim]["plasma"]["frequency_rad_s"],
            expected[sim]["plasma"]["frequency_rad_s"],
            rtol=1e-6, label=f"{sim}.plasma.frequency_rad_s",
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_wavelength(self, report, expected, sim):
        _assert_close(
            report[sim]["plasma"]["wavelength_m"],
            expected[sim]["plasma"]["wavelength_m"],
            rtol=1e-6, label=f"{sim}.plasma.wavelength_m",
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_skin_depth(self, report, expected, sim):
        _assert_close(
            report[sim]["plasma"]["skin_depth_m"],
            expected[sim]["plasma"]["skin_depth_m"],
            rtol=1e-6, label=f"{sim}.plasma.skin_depth_m",
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_critical_density(self, report, expected, sim):
        _assert_close(
            report[sim]["plasma"]["critical_density_m3"],
            expected[sim]["plasma"]["critical_density_m3"],
            rtol=1e-6, label=f"{sim}.plasma.critical_density_m3",
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_density_ratio(self, report, expected, sim):
        _assert_close(
            report[sim]["plasma"]["density_ratio"],
            expected[sim]["plasma"]["density_ratio"],
            rtol=1e-6, label=f"{sim}.plasma.density_ratio",
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_wavebreaking_field(self, report, expected, sim):
        _assert_close(
            report[sim]["plasma"]["wavebreaking_field_Vm"],
            expected[sim]["plasma"]["wavebreaking_field_Vm"],
            rtol=1e-6, label=f"{sim}.plasma.wavebreaking_field_Vm",
        )


# ---------------------------------------------------------------------------
# Tests: Resolution
# ---------------------------------------------------------------------------

class TestResolution:
    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_cells_per_laser_wavelength(self, report, expected, sim):
        _assert_close(
            report[sim]["resolution"]["cells_per_laser_wavelength"],
            expected[sim]["resolution"]["cells_per_laser_wavelength"],
            rtol=1e-6, label=f"{sim}.resolution.cells_per_laser_wavelength",
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_cells_per_skin_depth(self, report, expected, sim):
        _assert_close(
            report[sim]["resolution"]["cells_per_skin_depth"],
            expected[sim]["resolution"]["cells_per_skin_depth"],
            rtol=1e-6, label=f"{sim}.resolution.cells_per_skin_depth",
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_cells_per_plasma_wavelength(self, report, expected, sim):
        _assert_close(
            report[sim]["resolution"]["cells_per_plasma_wavelength"],
            expected[sim]["resolution"]["cells_per_plasma_wavelength"],
            rtol=1e-6, label=f"{sim}.resolution.cells_per_plasma_wavelength",
        )


# ---------------------------------------------------------------------------
# Tests: Numerical dispersion
# ---------------------------------------------------------------------------

class TestNumericalDispersion:
    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_phase_error(self, report, expected, sim):
        actual = report[sim]["numerical_dispersion"]["phase_error_pct"]
        exp = expected[sim]["numerical_dispersion"]["phase_error_pct"]
        assert abs(actual - exp) < 0.001, (
            f"{sim}.numerical_dispersion.phase_error_pct: "
            f"got {actual}, expected {exp}"
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_group_error(self, report, expected, sim):
        actual = report[sim]["numerical_dispersion"]["group_error_pct"]
        exp = expected[sim]["numerical_dispersion"]["group_error_pct"]
        assert abs(actual - exp) < 0.001, (
            f"{sim}.numerical_dispersion.group_error_pct: "
            f"got {actual}, expected {exp}"
        )


# ---------------------------------------------------------------------------
# Tests: Verdict
# ---------------------------------------------------------------------------

class TestVerdict:
    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_cfl_stable(self, report, expected, sim):
        assert report[sim]["verdict"]["cfl_stable"] == expected[sim]["verdict"]["cfl_stable"], (
            f"{sim}.verdict.cfl_stable: got {report[sim]['verdict']['cfl_stable']}, "
            f"expected {expected[sim]['verdict']['cfl_stable']}"
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_well_resolved(self, report, expected, sim):
        assert report[sim]["verdict"]["well_resolved"] == expected[sim]["verdict"]["well_resolved"], (
            f"{sim}.verdict.well_resolved: got {report[sim]['verdict']['well_resolved']}, "
            f"expected {expected[sim]['verdict']['well_resolved']}"
        )


# ---------------------------------------------------------------------------
# Tests: Physics sanity checks
# ---------------------------------------------------------------------------

class TestPhysicsSanity:
    """Cross-checks for internal consistency of each simulation."""

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_density_below_critical(self, report, sim):
        """Laser must propagate: n_e < n_c."""
        assert report[sim]["plasma"]["density_ratio"] < 1.0, (
            f"{sim}: density_ratio >= 1 means laser cannot propagate"
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_phase_velocity_below_c(self, report, sim):
        """Yee FDTD numerical phase velocity should be <= c."""
        assert report[sim]["numerical_dispersion"]["phase_error_pct"] <= 0.0, (
            f"{sim}: phase velocity should not exceed c for Yee scheme"
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_group_velocity_below_c(self, report, sim):
        """Yee FDTD numerical group velocity should be <= c."""
        assert report[sim]["numerical_dispersion"]["group_error_pct"] <= 0.0, (
            f"{sim}: group velocity should not exceed c for Yee scheme"
        )

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_skin_depth_consistent(self, report, sim):
        """skin_depth = plasma_wavelength / (2*pi)."""
        sd = report[sim]["plasma"]["skin_depth_m"]
        lp = report[sim]["plasma"]["wavelength_m"]
        expected_sd = lp / (2.0 * np.pi)
        _assert_close(sd, expected_sd, rtol=1e-6,
                       label=f"{sim}: skin_depth vs wavelength/(2pi)")

    def test_lpa_fine_well_resolved(self, report):
        """lpa_fine should be well resolved."""
        assert report["lpa_fine"]["verdict"]["well_resolved"] is True

    def test_lpa_coarse_not_well_resolved(self, report):
        """lpa_coarse should NOT be well resolved."""
        assert report["lpa_coarse"]["verdict"]["well_resolved"] is False

    def test_lpa_dense_well_resolved(self, report):
        """lpa_dense should be well resolved."""
        assert report["lpa_dense"]["verdict"]["well_resolved"] is True

    @pytest.mark.parametrize("sim", SIM_NAMES)
    def test_all_cfl_stable(self, report, sim):
        """All three configurations should be CFL stable."""
        assert report[sim]["verdict"]["cfl_stable"] is True
