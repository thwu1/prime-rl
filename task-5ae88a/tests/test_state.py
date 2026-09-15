"""
Tests for the MHD solver pipeline.
Verifies physical conservation laws, divergence-free condition,
quantitative diagnostics, and required output artifacts.

"""

import pytest
import json
import os
import re
import numpy as np


@pytest.fixture(scope="module")
def results():
    """Load the simulation results from /app/results.json."""
    results_path = "/app/results.json"
    assert os.path.exists(results_path), (
        f"Results file not found at {results_path}. "
        "Did you run the MHD solver?"
    )
    with open(results_path) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def config():
    """Load the simulation config."""
    with open("/app/config.json") as f:
        return json.load(f)


class TestResultsExist:
    """Verify all required fields are present in results."""

    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_required_fields(self, results):
        required = [
            "total_mass", "total_energy", "total_momx", "total_momy",
            "max_divB", "max_density", "min_density", "mean_density",
            "magnetic_energy", "kinetic_energy", "internal_energy", "num_steps",
        ]
        for field in required:
            assert field in results, f"Missing required field: {field}"

    def test_solver_file_exists(self):
        assert os.path.exists("/app/mhd_solver.py"), "mhd_solver.py not found"


class TestConservation:
    """Verify that the solver conserves mass, energy, and momentum."""

    def test_mass_conservation(self, results, config):
        """Total mass must be conserved to machine precision."""
        gamma = config["gamma"]
        expected_mass = gamma**2 / (4 * np.pi)
        rel_error = abs(results["total_mass"] - expected_mass) / expected_mass
        assert rel_error < 1e-10, (
            f"Mass not conserved: total_mass={results['total_mass']}, "
            f"expected={expected_mass}, relative error={rel_error}"
        )

    def test_energy_conservation(self, results):
        """Total energy must be conserved (conservative scheme)."""
        ref_energy = 0.34923671241932386
        rel_error = abs(results["total_energy"] - ref_energy) / ref_energy
        assert rel_error < 1e-6, (
            f"Energy not conserved: total_energy={results['total_energy']}, "
            f"expected~{ref_energy}, relative error={rel_error}"
        )

    def test_momentum_x_conservation(self, results):
        """Total x-momentum must be ~0 (by symmetry of initial conditions)."""
        assert abs(results["total_momx"]) < 1e-10, (
            f"X-momentum not conserved: total_momx={results['total_momx']}"
        )

    def test_momentum_y_conservation(self, results):
        """Total y-momentum must be ~0 (by symmetry of initial conditions)."""
        assert abs(results["total_momy"]) < 1e-10, (
            f"Y-momentum not conserved: total_momy={results['total_momy']}"
        )


class TestDivergenceFree:
    """Verify the divergence-free condition for the magnetic field."""

    def test_divB_machine_precision(self, results):
        """Divergence of B must be maintained to near machine precision."""
        assert results["max_divB"] < 1e-10, (
            f"Divergence-free condition violated: max|divB|={results['max_divB']}"
        )


class TestDensityStructure:
    """Verify the density field has the expected structure at t=0.5."""

    def test_mean_density(self, results, config):
        """Mean density should equal initial uniform density."""
        gamma = config["gamma"]
        expected = gamma**2 / (4 * np.pi)
        rel_error = abs(results["mean_density"] - expected) / expected
        assert rel_error < 1e-10, (
            f"Mean density wrong: {results['mean_density']} vs expected {expected}"
        )

    def test_max_density_range(self, results):
        """Peak density from shock compression should be in expected range."""
        assert 0.35 < results["max_density"] < 0.50, (
            f"Max density {results['max_density']} outside expected range [0.35, 0.50]"
        )

    def test_min_density_range(self, results):
        """Minimum density from rarefactions should be in expected range."""
        assert 0.06 < results["min_density"] < 0.15, (
            f"Min density {results['min_density']} outside expected range [0.06, 0.15]"
        )

    def test_density_positive(self, results):
        """Density must be positive everywhere."""
        assert results["min_density"] > 0, (
            f"Negative density detected: min_density={results['min_density']}"
        )


class TestEnergyPartition:
    """Verify the energy partition at the final time."""

    def test_magnetic_energy_range(self, results):
        assert 0.04 < results["magnetic_energy"] < 0.08, (
            f"Magnetic energy {results['magnetic_energy']} outside expected range [0.04, 0.08]"
        )

    def test_kinetic_energy_range(self, results):
        assert 0.02 < results["kinetic_energy"] < 0.07, (
            f"Kinetic energy {results['kinetic_energy']} outside expected range [0.02, 0.07]"
        )

    def test_internal_energy_range(self, results):
        assert 0.20 < results["internal_energy"] < 0.30, (
            f"Internal energy {results['internal_energy']} outside expected range [0.20, 0.30]"
        )

    def test_energy_partition_sum(self, results):
        """Sum of energy components should equal total energy."""
        component_sum = (
            results["magnetic_energy"]
            + results["kinetic_energy"]
            + results["internal_energy"]
        )
        rel_error = abs(component_sum - results["total_energy"]) / results["total_energy"]
        assert rel_error < 1e-6, (
            f"Energy partition inconsistent: components sum to {component_sum} "
            f"but total_energy={results['total_energy']}, relative error={rel_error}"
        )

    def test_magnetic_energy_decreased(self, results):
        """Magnetic energy should decrease from initial value due to dissipation."""
        assert results["magnetic_energy"] < 0.065, (
            f"Magnetic energy {results['magnetic_energy']} appears too high"
        )


class TestSimulationBehavior:
    """Verify the simulation ran correctly."""

    def test_num_steps_reasonable(self, results):
        """Number of timesteps should be in a reasonable range."""
        assert 300 < results["num_steps"] < 600, (
            f"Number of steps {results['num_steps']} outside expected range [300, 600]"
        )


class TestDensityOutput:
    """Verify the density data file is correct."""

    def test_density_dat_exists(self):
        assert os.path.exists("/app/density_final.dat"), (
            "density_final.dat not found at /app/"
        )

    def test_density_dat_dimensions(self, config):
        """density_final.dat should be an NxN matrix."""
        data = np.loadtxt("/app/density_final.dat")
        N = config["N"]
        assert data.shape == (N, N), (
            f"Expected ({N},{N}), got {data.shape}"
        )

    def test_density_dat_stats_match(self, results):
        """Statistics from density_final.dat should match results.json."""
        data = np.loadtxt("/app/density_final.dat")
        assert abs(np.max(data) - results["max_density"]) < 1e-6, (
            f"Max density mismatch: dat={np.max(data)}, json={results['max_density']}"
        )
        assert abs(np.min(data) - results["min_density"]) < 1e-6, (
            f"Min density mismatch: dat={np.min(data)}, json={results['min_density']}"
        )
        assert abs(np.mean(data) - results["mean_density"]) < 1e-6, (
            f"Mean density mismatch: dat={np.mean(data)}, json={results['mean_density']}"
        )


class TestPlotOutput:
    """Verify the density contour plot was generated correctly."""

    def test_density_contour_png_exists(self):
        assert os.path.exists("/app/density_contour.png"), (
            "density_contour.png not found at /app/"
        )

    def test_density_contour_png_valid(self):
        """Verify the PNG file has valid PNG magic bytes."""
        with open("/app/density_contour.png", "rb") as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', (
            "density_contour.png is not a valid PNG file"
        )

    def test_density_contour_png_nontrivial(self):
        """PNG should be non-trivial (> 1KB)."""
        size = os.path.getsize("/app/density_contour.png")
        assert size > 1024, (
            f"PNG file too small ({size} bytes), likely corrupt or empty"
        )


class TestMakefile:
    """Verify the Makefile exists with required targets."""

    def test_makefile_exists(self):
        assert os.path.exists("/app/Makefile"), "Makefile not found at /app/"

    def test_makefile_has_run_target(self):
        with open("/app/Makefile") as f:
            content = f.read()
        assert re.search(r'^run\s*:', content, re.MULTILINE), (
            "Makefile missing 'run:' target"
        )

    def test_makefile_has_plot_target(self):
        with open("/app/Makefile") as f:
            content = f.read()
        assert re.search(r'^plot\s*:', content, re.MULTILINE), (
            "Makefile missing 'plot:' target"
        )

    def test_makefile_has_all_target(self):
        with open("/app/Makefile") as f:
            content = f.read()
        assert re.search(r'^all\s*:', content, re.MULTILINE), (
            "Makefile missing 'all:' target"
        )
