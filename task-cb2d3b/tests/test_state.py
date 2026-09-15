
"""
Tests for the MHD Orszag-Tang vortex simulation.
Verifies HDF5 output, Makefile targets, gnuplot plots,
and physical correctness of the simulation results.
"""

import h5py
import json
import os
import re
import subprocess
import numpy as np
import pytest


OUTPUT_DIR = "/app/output"
H5_PATH = os.path.join(OUTPUT_DIR, "results.h5")


class TestOutputFilesExist:
    """Verify all required output files are present."""

    def test_hdf5_exists(self):
        assert os.path.isfile(H5_PATH), "results.h5 not found"

    def test_params_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, "params.json"))

    def test_density_plot_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, "density_contour.png"))

    def test_divB_plot_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, "divB_map.png"))

    def test_density_gp_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, "density.gp"))

    def test_divB_gp_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, "divB.gp"))


class TestMakefile:
    """Verify the Makefile exists and has the required targets."""

    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile")

    def test_makefile_has_run_target(self):
        with open("/app/Makefile", "r") as f:
            content = f.read()
        assert re.search(r'^run\s*:', content, re.MULTILINE), \
            "Makefile missing 'run' target"

    def test_makefile_has_plots_target(self):
        with open("/app/Makefile", "r") as f:
            content = f.read()
        assert re.search(r'^plots\s*:', content, re.MULTILINE), \
            "Makefile missing 'plots' target"

    def test_makefile_has_all_target(self):
        with open("/app/Makefile", "r") as f:
            content = f.read()
        assert re.search(r'^all\s*:', content, re.MULTILINE), \
            "Makefile missing 'all' target"

    def test_makefile_has_clean_target(self):
        with open("/app/Makefile", "r") as f:
            content = f.read()
        assert re.search(r'^clean\s*:', content, re.MULTILINE), \
            "Makefile missing 'clean' target"

    def test_makefile_valid_syntax(self):
        result = subprocess.run(
            ["make", "-n", "all"], capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"make -n all failed: {result.stderr}"


class TestHDF5Structure:
    """Verify HDF5 file structure and dataset shapes."""

    def test_h5ls_works(self):
        result = subprocess.run(
            ["h5ls", H5_PATH], capture_output=True, text=True
        )
        assert result.returncode == 0, f"h5ls failed: {result.stderr}"
        for name in ["density", "divB", "Bx", "By",
                      "mass_history", "energy_history"]:
            assert name in result.stdout, \
                f"Dataset '{name}' not found by h5ls"

    def test_density_shape(self):
        with h5py.File(H5_PATH, "r") as f:
            assert f["density"].shape == (128, 128)

    def test_divB_shape(self):
        with h5py.File(H5_PATH, "r") as f:
            assert f["divB"].shape == (128, 128)

    def test_Bx_shape(self):
        with h5py.File(H5_PATH, "r") as f:
            assert f["Bx"].shape == (128, 128)

    def test_By_shape(self):
        with h5py.File(H5_PATH, "r") as f:
            assert f["By"].shape == (128, 128)

    def test_mass_history_1d(self):
        with h5py.File(H5_PATH, "r") as f:
            arr = f["mass_history"][:]
            assert arr.ndim == 1
            assert len(arr) > 50

    def test_energy_history_1d(self):
        with h5py.File(H5_PATH, "r") as f:
            arr = f["energy_history"][:]
            assert arr.ndim == 1
            assert len(arr) > 50


class TestParameters:
    """Verify simulation parameters match specification."""

    def test_params_values(self):
        with open(os.path.join(OUTPUT_DIR, "params.json"), "r") as f:
            params = json.load(f)
        assert params["N"] == 128
        assert abs(params["gamma"] - 5.0 / 3.0) < 1e-10
        assert abs(params["tEnd"] - 0.5) < 1e-10
        assert abs(params["courant_fac"] - 0.4) < 1e-10


class TestDivergenceFreeB:
    """The solenoidal constraint must hold to machine precision."""

    def test_divB_zero(self):
        with h5py.File(H5_PATH, "r") as f:
            divB = f["divB"][:]
        max_divB = np.max(np.abs(divB))
        assert max_divB < 1e-10, (
            f"max|divB| = {max_divB:.2e}; must be zero to machine precision"
        )


class TestConservation:
    """Total mass and energy must be conserved on the periodic domain."""

    def test_mass_conservation(self):
        with h5py.File(H5_PATH, "r") as f:
            mass = f["mass_history"][:]
        rel_change = np.abs(mass - mass[0]) / np.abs(mass[0])
        assert np.max(rel_change) < 1e-10, (
            f"Mass not conserved: max relative change = "
            f"{np.max(rel_change):.2e}"
        )

    def test_energy_conservation(self):
        with h5py.File(H5_PATH, "r") as f:
            energy = f["energy_history"][:]
        rel_change = np.abs(energy - energy[0]) / np.abs(energy[0])
        assert np.max(rel_change) < 1e-10, (
            f"Energy not conserved: max relative change = "
            f"{np.max(rel_change):.2e}"
        )


class TestDensityField:
    """Verify physical properties of the density field."""

    def test_density_positive(self):
        with h5py.File(H5_PATH, "r") as f:
            rho = f["density"][:]
        assert np.all(rho > 0), "Density must be strictly positive"

    def test_density_nontrivial(self):
        with h5py.File(H5_PATH, "r") as f:
            rho = f["density"][:]
        std_rho = np.std(rho)
        assert std_rho > 0.01, (
            f"Density std = {std_rho:.4f}; expected significant structure"
        )

    def test_density_range(self):
        with h5py.File(H5_PATH, "r") as f:
            rho = f["density"][:]
        assert np.max(rho) > 0.25, (
            f"max(rho) = {np.max(rho):.4f}; expected shock compression"
        )
        assert np.min(rho) < 0.20, (
            f"min(rho) = {np.min(rho):.4f}; expected rarefaction"
        )

    def test_mean_density_conserved(self):
        with h5py.File(H5_PATH, "r") as f:
            rho = f["density"][:]
        gamma = 5.0 / 3.0
        expected_mean = gamma**2 / (4.0 * np.pi)
        actual_mean = np.mean(rho)
        rel_error = abs(actual_mean - expected_mean) / expected_mean
        assert rel_error < 1e-6, (
            f"Mean density {actual_mean:.6f} != expected "
            f"{expected_mean:.6f} (rel error {rel_error:.2e})"
        )


class TestDensitySymmetry:
    """The Orszag-Tang vortex has 180-degree rotational symmetry."""

    def test_180_rotation_symmetry(self):
        with h5py.File(H5_PATH, "r") as f:
            rho = f["density"][:]
        rho_rotated = rho[::-1, ::-1]
        max_diff = np.max(np.abs(rho - rho_rotated))
        assert max_diff < 1e-8, (
            f"Density not symmetric under 180-degree rotation: "
            f"max difference = {max_diff:.2e}"
        )


class TestMagneticField:
    """Verify magnetic field properties."""

    def test_B_nonzero(self):
        with h5py.File(H5_PATH, "r") as f:
            Bx = f["Bx"][:]
            By = f["By"][:]
        B2_mean = np.mean(Bx**2 + By**2)
        assert B2_mean > 1e-4, (
            f"mean(B^2) = {B2_mean:.2e}; magnetic field too weak"
        )

    def test_B_bounded(self):
        with h5py.File(H5_PATH, "r") as f:
            Bx = f["Bx"][:]
            By = f["By"][:]
        B2_max = np.max(Bx**2 + By**2)
        assert B2_max < 10.0, (
            f"max(B^2) = {B2_max:.2e}; magnetic field blowing up"
        )

    def test_B_antisymmetry(self):
        with h5py.File(H5_PATH, "r") as f:
            Bx = f["Bx"][:]
            By = f["By"][:]
        max_diff_Bx = np.max(np.abs(Bx + Bx[::-1, ::-1]))
        max_diff_By = np.max(np.abs(By + By[::-1, ::-1]))
        assert max_diff_Bx < 1e-8, (
            f"Bx antisymmetry violated: max diff = {max_diff_Bx:.2e}"
        )
        assert max_diff_By < 1e-8, (
            f"By antisymmetry violated: max diff = {max_diff_By:.2e}"
        )

    def test_magnetic_energy_fraction(self):
        with h5py.File(H5_PATH, "r") as f:
            Bx = f["Bx"][:]
            By = f["By"][:]
            energy = f["energy_history"][:]
        N = 128
        dx = 1.0 / N
        vol = dx**2
        magnetic_energy = np.sum(0.5 * (Bx**2 + By**2) * vol)
        total_energy = energy[-1]
        frac = magnetic_energy / total_energy
        assert 0.05 < frac < 0.6, (
            f"Magnetic energy fraction = {frac:.4f}; "
            f"expected between 0.05 and 0.6"
        )


class TestPlots:
    """Verify diagnostic plots exist and are non-trivial."""

    def test_density_png_size(self):
        path = os.path.join(OUTPUT_DIR, "density_contour.png")
        assert os.path.getsize(path) > 100, \
            "density_contour.png is too small"

    def test_divB_png_size(self):
        path = os.path.join(OUTPUT_DIR, "divB_map.png")
        assert os.path.getsize(path) > 100, \
            "divB_map.png is too small"

    def test_gp_scripts_valid(self):
        for name in ["density.gp", "divB.gp"]:
            path = os.path.join(OUTPUT_DIR, name)
            with open(path, "r") as f:
                content = f.read()
            assert "set term" in content, \
                f"{name} does not contain valid gnuplot commands"
