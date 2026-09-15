"""Tests for the 1D compressible Navier-Stokes solver.

"""
import os
import sys
import urllib.request

import h5py
import numpy as np
import pytest

# Use the development dataset (smaller, faster download and evaluation)
DATA_URL = (
    "https://huggingface.co/datasets/LDA1020/codepde-data/resolve/main/"
    "cns1d/1D_CFD_Rand_Eta0.1_Zeta0.1_periodic_Train_development.hdf5"
)
DATA_PATH = "/app/data/cns1d_dev.hdf5"

ETA = 0.1
ZETA = 0.1
NRMSE_THRESHOLD = 0.05

# Cap the number of samples to keep runtime manageable in pure NumPy
MAX_TEST_SAMPLES = 20


def _download():
    if not os.path.exists(DATA_PATH):
        os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
        urllib.request.urlretrieve(DATA_URL, DATA_PATH)


def _load_data():
    _download()
    with h5py.File(DATA_PATH, "r") as f:
        t_coordinate = np.array(f["t-coordinate"])
        Vx = np.array(f["Vx"])[:MAX_TEST_SAMPLES]
        density = np.array(f["density"])[:MAX_TEST_SAMPLES]
        pressure = np.array(f["pressure"])[:MAX_TEST_SAMPLES]
    return t_coordinate, Vx, density, pressure


def _get_solver():
    sys.path.insert(0, "/app")
    if "solver" in sys.modules:
        del sys.modules["solver"]
    from solver import solver
    return solver


def _compute_nrmse(pred, ref):
    """Compute nRMSE. Arrays shape [batch, T+1, N, 3]."""
    rmse = np.sqrt(np.mean((pred - ref) ** 2, axis=(1, 2, 3)))
    norm = np.sqrt(np.mean(ref ** 2, axis=(1, 2, 3)))
    return float(np.mean(rmse / norm))


# ---- Module-scoped fixtures so the solver runs only once ----

@pytest.fixture(scope="module")
def reference_data():
    """Load reference HDF5 data (downloaded once)."""
    return _load_data()


@pytest.fixture(scope="module")
def solver_predictions(reference_data):
    """Run solver on reference data once for all accuracy tests."""
    t_coord, Vx, density, pressure = reference_data
    solver_fn = _get_solver()
    Vx_pred, density_pred, pressure_pred = solver_fn(
        Vx[:, 0], density[:, 0], pressure[:, 0], t_coord, ETA, ZETA
    )
    return Vx_pred, density_pred, pressure_pred


# ---- Basic tests (no reference data needed) ----

class TestSolverBasic:
    """Basic checks that do not require reference data."""

    def test_solver_function_exists(self):
        solver = _get_solver()
        assert callable(solver), "solver must be callable"

    def test_solver_output_shape_small(self):
        """Run on a tiny synthetic input to verify shapes."""
        solver = _get_solver()
        B, N, T = 2, 64, 5
        Vx0 = np.random.randn(B, N).astype(np.float32) * 0.1
        density0 = np.ones((B, N), dtype=np.float32)
        pressure0 = np.ones((B, N), dtype=np.float32)
        t_coord = np.linspace(0, 0.01, T + 1).astype(np.float32)

        Vx_pred, density_pred, pressure_pred = solver(
            Vx0, density0, pressure0, t_coord, ETA, ZETA
        )

        assert Vx_pred.shape == (B, T + 1, N), \
            f"Vx shape {Vx_pred.shape} != expected {(B, T + 1, N)}"
        assert density_pred.shape == (B, T + 1, N)
        assert pressure_pred.shape == (B, T + 1, N)

    def test_initial_condition_preserved(self):
        """First time-frame of output must match the initial condition."""
        solver = _get_solver()
        B, N = 2, 64
        Vx0 = np.random.randn(B, N).astype(np.float32) * 0.1
        density0 = np.ones((B, N), dtype=np.float32) * 2.0
        pressure0 = np.ones((B, N), dtype=np.float32) * 3.0
        t_coord = np.array([0.0, 0.001], dtype=np.float32)

        Vx_pred, density_pred, pressure_pred = solver(
            Vx0, density0, pressure0, t_coord, ETA, ZETA
        )

        np.testing.assert_allclose(Vx_pred[:, 0], Vx0, atol=1e-5)
        np.testing.assert_allclose(density_pred[:, 0], density0, atol=1e-5)
        np.testing.assert_allclose(pressure_pred[:, 0], pressure0, atol=1e-5)


# ---- Accuracy tests against reference PDEBench data ----

class TestSolverAccuracy:
    """Accuracy tests using module-scoped fixtures (solver runs once)."""

    def test_output_shapes_match_reference(self, reference_data, solver_predictions):
        t_coord, Vx, density, pressure = reference_data
        Vx_pred, density_pred, pressure_pred = solver_predictions

        assert Vx_pred.shape == Vx.shape, \
            f"Vx shape {Vx_pred.shape} != {Vx.shape}"
        assert density_pred.shape == density.shape, \
            f"density shape {density_pred.shape} != {density.shape}"
        assert pressure_pred.shape == pressure.shape, \
            f"pressure shape {pressure_pred.shape} != {pressure.shape}"

    def test_no_nan_in_output(self, solver_predictions):
        Vx_pred, density_pred, pressure_pred = solver_predictions

        assert not np.isnan(Vx_pred).any(), "Vx contains NaN"
        assert not np.isnan(density_pred).any(), "density contains NaN"
        assert not np.isnan(pressure_pred).any(), "pressure contains NaN"

    def test_nrmse_below_threshold(self, reference_data, solver_predictions):
        t_coord, Vx, density, pressure = reference_data
        Vx_pred, density_pred, pressure_pred = solver_predictions

        stacked_pred = np.stack(
            [Vx_pred, density_pred, pressure_pred], axis=-1
        )
        stacked_ref = np.stack([Vx, density, pressure], axis=-1)

        nrmse = _compute_nrmse(stacked_pred, stacked_ref)
        print(f"nRMSE = {nrmse:.6f} (threshold = {NRMSE_THRESHOLD})")

        assert nrmse < NRMSE_THRESHOLD, \
            f"nRMSE = {nrmse:.6f}, expected < {NRMSE_THRESHOLD}"
