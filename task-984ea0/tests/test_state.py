
import numpy as np
import h5py
import pytest
import ctypes
import os
import sys

sys.path.insert(0, "/app")


# ═══════════════════════════════════════════════════════════════════════
# C LIBRARY VALIDATION TESTS
# ═══════════════════════════════════════════════════════════════════════

def test_c_library_loadable():
    """The compiled C stencil library must exist and export required symbols."""
    lib_path = "/app/src/libkernels.so"
    assert os.path.exists(lib_path), (
        f"C library not found at {lib_path}. Must be compiled with: make -C /app/src"
    )
    lib = ctypes.CDLL(lib_path)
    for fname in ["compute_rhs", "euler_step", "compute_cfl_timestep", "has_nan"]:
        fn = getattr(lib, fname, None)
        assert fn is not None, f"Symbol '{fname}' not exported from {lib_path}"


def _load_lib():
    """Helper: load the C library and set up function signatures."""
    lib = ctypes.CDLL("/app/src/libkernels.so")
    DP = ctypes.POINTER(ctypes.c_double)
    lib.compute_rhs.argtypes = [
        DP, DP, DP, DP, DP, DP,
        ctypes.c_int, ctypes.c_double, ctypes.c_double, ctypes.c_double,
        ctypes.c_double, ctypes.c_double,
    ]
    lib.compute_rhs.restype = None
    lib.euler_step.argtypes = [
        DP, DP, DP, DP, DP, DP, ctypes.c_int, ctypes.c_double,
    ]
    lib.euler_step.restype = None
    lib.compute_cfl_timestep.argtypes = [
        DP, DP, DP, ctypes.c_int,
        ctypes.c_double, ctypes.c_double, ctypes.c_double,
        ctypes.c_double, ctypes.c_double, ctypes.c_double,
    ]
    lib.compute_cfl_timestep.restype = ctypes.c_double
    lib.has_nan.argtypes = [DP, ctypes.c_int]
    lib.has_nan.restype = ctypes.c_int
    return lib


def _ptr(arr):
    return arr.ctypes.data_as(ctypes.POINTER(ctypes.c_double))


def test_c_compute_rhs_nontrivial():
    """C compute_rhs must produce non-zero, NaN-free output for sinusoidal input."""
    lib = _load_lib()
    N = 32
    x = np.linspace(-1, 1, N)
    Vx = np.ascontiguousarray(np.sin(np.pi * x), dtype=np.float64)
    den = np.ascontiguousarray(1.0 + 0.1 * np.cos(np.pi * x), dtype=np.float64)
    pres = np.ascontiguousarray(1.0 + 0.1 * np.cos(2 * np.pi * x), dtype=np.float64)
    drho = np.zeros(N, dtype=np.float64)
    dv = np.zeros(N, dtype=np.float64)
    dp = np.zeros(N, dtype=np.float64)

    lib.compute_rhs(
        _ptr(Vx), _ptr(den), _ptr(pres),
        _ptr(drho), _ptr(dv), _ptr(dp),
        N, 2.0 / (N - 1), 0.1, 0.1, 5.0 / 3.0, 1.5,
    )
    assert not np.all(drho == 0), "drho_dt is all zeros — compute_rhs not implemented"
    assert not np.all(dv == 0), "dv_dt is all zeros — compute_rhs not implemented"
    assert not np.all(dp == 0), "dp_dt is all zeros — compute_rhs not implemented"
    assert not np.any(np.isnan(drho)), "NaN in drho_dt"
    assert not np.any(np.isnan(dv)), "NaN in dv_dt"
    assert not np.any(np.isnan(dp)), "NaN in dp_dt"


def test_c_euler_step():
    """C euler_step must perform correct forward-Euler updates."""
    lib = _load_lib()
    N = 10
    Vx = np.ones(N, dtype=np.float64)
    den = np.ones(N, dtype=np.float64)
    pres = np.ones(N, dtype=np.float64)
    drho = np.full(N, 0.5, dtype=np.float64)
    dv = np.full(N, -0.5, dtype=np.float64)
    dp_arr = np.full(N, 0.5, dtype=np.float64)

    lib.euler_step(
        _ptr(Vx), _ptr(den), _ptr(pres),
        _ptr(drho), _ptr(dv), _ptr(dp_arr),
        N, 0.01,
    )
    np.testing.assert_allclose(Vx, 1.0 + 0.01 * (-0.5), rtol=1e-12,
                               err_msg="euler_step velocity update wrong")
    np.testing.assert_allclose(den, 1.0 + 0.01 * 0.5, rtol=1e-12,
                               err_msg="euler_step density update wrong")
    np.testing.assert_allclose(pres, 1.0 + 0.01 * 0.5, rtol=1e-12,
                               err_msg="euler_step pressure update wrong")


def test_c_cfl_timestep():
    """C compute_cfl_timestep must return a reasonable positive timestep."""
    lib = _load_lib()
    N = 64
    Vx = np.zeros(N, dtype=np.float64)
    den = np.ones(N, dtype=np.float64)
    pres = np.ones(N, dtype=np.float64)
    dx = 2.0 / (N - 1)

    dt = lib.compute_cfl_timestep(
        _ptr(Vx), _ptr(den), _ptr(pres),
        N, dx, 5.0 / 3.0, 0.1, 1e-7, 1e-3, 1.0,
    )
    assert dt > 0, f"CFL timestep must be positive, got {dt}"
    assert dt <= 1e-3, f"CFL timestep {dt} exceeds max_dt=1e-3"


# ═══════════════════════════════════════════════════════════════════════
# SOLVER ACCURACY TESTS
# ═══════════════════════════════════════════════════════════════════════

def compute_nrmse(u_computed, u_reference):
    """Compute nRMSE over stacked [batch, time, space, 3] arrays."""
    rmse_values = np.sqrt(
        np.mean((u_computed - u_reference) ** 2, axis=(1, 2, 3))
    )
    u_true_norm = np.sqrt(np.mean(u_reference ** 2, axis=(1, 2, 3)))
    return np.mean(rmse_values / u_true_norm)


@pytest.fixture(scope="module")
def h5data():
    """Load HDF5 reference data."""
    with h5py.File("/app/data/reference.h5", "r") as f:
        data = {}
        for regime in f.keys():
            grp = f[regime]
            data[regime] = {
                "Vx0": grp["initial_conditions/velocity"][:],
                "density0": grp["initial_conditions/density"][:],
                "pressure0": grp["initial_conditions/pressure"][:],
                "Vx_ref": grp["reference_solution/velocity"][:],
                "density_ref": grp["reference_solution/density"][:],
                "pressure_ref": grp["reference_solution/pressure"][:],
                "t_coordinate": grp["t_coordinate"][:],
                "eta": float(grp.attrs["eta"]),
                "zeta": float(grp.attrs["zeta"]),
            }
    return data


@pytest.fixture(scope="module")
def solver_results(h5data):
    """Run the solver for all regimes and cache results."""
    from solver import solver

    results = {}
    for regime, rd in h5data.items():
        Vx, den, pres = solver(
            rd["Vx0"],
            rd["density0"],
            rd["pressure0"],
            rd["t_coordinate"],
            rd["eta"],
            rd["zeta"],
        )
        results[regime] = (Vx, den, pres)
    return results


def test_solver_callable():
    """The solver module must export a callable 'solver' function."""
    from solver import solver

    assert callable(solver)


@pytest.mark.parametrize("regime", ["high_viscosity", "low_viscosity"])
def test_output_shapes(solver_results, h5data, regime):
    """Solver output arrays must have the correct shapes."""
    Vx, den, pres = solver_results[regime]
    expected = h5data[regime]["Vx_ref"].shape
    assert Vx.shape == expected, f"Vx: {Vx.shape} != {expected}"
    assert den.shape == expected, f"density: {den.shape} != {expected}"
    assert pres.shape == expected, f"pressure: {pres.shape} != {expected}"


@pytest.mark.parametrize("regime", ["high_viscosity", "low_viscosity"])
def test_no_nans(solver_results, regime):
    """Solver output must not contain NaN values."""
    Vx, den, pres = solver_results[regime]
    assert not np.isnan(Vx).any(), "NaN in velocity"
    assert not np.isnan(den).any(), "NaN in density"
    assert not np.isnan(pres).any(), "NaN in pressure"


@pytest.mark.parametrize("regime", ["high_viscosity", "low_viscosity"])
def test_initial_conditions_preserved(solver_results, h5data, regime):
    """First time frame must match initial conditions."""
    Vx, den, pres = solver_results[regime]
    rd = h5data[regime]
    np.testing.assert_allclose(
        Vx[:, 0], rd["Vx0"], rtol=1e-10,
        err_msg="Initial velocity not preserved",
    )
    np.testing.assert_allclose(
        den[:, 0], rd["density0"], rtol=1e-10,
        err_msg="Initial density not preserved",
    )
    np.testing.assert_allclose(
        pres[:, 0], rd["pressure0"], rtol=1e-10,
        err_msg="Initial pressure not preserved",
    )


@pytest.mark.parametrize("regime", ["high_viscosity", "low_viscosity"])
def test_nrmse_below_threshold(solver_results, h5data, regime):
    """Overall nRMSE must be below 0.05 for each regime."""
    Vx, den, pres = solver_results[regime]
    rd = h5data[regime]
    stacked_pred = np.stack([Vx, den, pres], axis=-1)
    stacked_ref = np.stack(
        [rd["Vx_ref"], rd["density_ref"], rd["pressure_ref"]], axis=-1
    )
    nrmse = compute_nrmse(stacked_pred, stacked_ref)
    assert nrmse < 0.05, f"{regime}: nRMSE = {nrmse:.6f} >= 0.05"


def _generate_convergence_ic(N, seed=123):
    """Generate smooth initial conditions for convergence testing."""
    rng = np.random.default_rng(seed)
    x = np.linspace(-1, 1, N)
    batch = 2
    amps = rng.standard_normal((batch, 3, 3))

    Vx0 = np.zeros((batch, N), dtype=np.float64)
    den0 = np.ones((batch, N), dtype=np.float64)
    pres0 = np.ones((batch, N), dtype=np.float64)

    for b in range(batch):
        for ki, k in enumerate([1, 2, 3]):
            Vx0[b] += 0.1 * amps[b, 0, ki] * np.sin(k * np.pi * x)
            den0[b] += 0.05 * amps[b, 1, ki] * np.cos(k * np.pi * x)
            pres0[b] += 0.05 * amps[b, 2, ki] * np.cos(k * np.pi * x)

    den0 = np.clip(den0, 0.5, 2.0)
    pres0 = np.clip(pres0, 0.5, 2.0)

    return Vx0, den0, pres0


def test_convergence_rate():
    """Solver must demonstrate spatial convergence (rate > 1.3)."""
    from solver import solver
    from scipy.interpolate import make_interp_spline

    resolutions = [64, 128, 256]
    eta, zeta = 0.1, 0.1
    t_coord = np.linspace(0, 0.01, 3)

    solutions = {}
    for N in resolutions:
        Vx0, den0, pres0 = _generate_convergence_ic(N, seed=123)
        Vx, den, pres = solver(Vx0, den0, pres0, t_coord, eta, zeta)
        solutions[N] = (Vx, den, pres)

    errors = []
    for i in range(len(resolutions) - 1):
        Nc = resolutions[i]
        Nf = resolutions[i + 1]
        xc = np.linspace(-1, 1, Nc)
        xf = np.linspace(-1, 1, Nf)

        total_err = 0.0
        for vi in range(3):
            sol_c = solutions[Nc][vi]
            sol_f = solutions[Nf][vi]
            batch_sz, n_times, _ = sol_c.shape

            interp_c = np.zeros(
                (batch_sz, n_times, Nf), dtype=np.float64
            )
            for b in range(batch_sz):
                for t in range(n_times):
                    spl = make_interp_spline(xc, sol_c[b, t], k=3)
                    interp_c[b, t] = spl(xf)

            total_err += np.sqrt(np.mean((interp_c - sol_f) ** 2))

        errors.append(total_err / 3.0)

    assert len(errors) == 2, "Expected errors for two resolution pairs"
    assert errors[1] > 0, "Fine-grid error is zero — cannot compute rate"
    rate = np.log2(errors[0] / errors[1])
    assert rate > 1.3, (
        f"Convergence rate = {rate:.2f} < 1.3 "
        f"(errors: {errors[0]:.2e}, {errors[1]:.2e})"
    )
