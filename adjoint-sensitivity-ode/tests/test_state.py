
import csv
import json
import sys
import tomllib

sys.path.insert(0, '/app')

import numpy as np
from scipy.integrate import solve_ivp

from system import lotka_volterra, TRUE_PARAMS, Y0


def _load_observations():
    """Load observation data from the pipeline's CSV and TOML files."""
    times = []
    y_obs = []
    with open('/app/data/observations.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            times.append(float(row['time']))
            y_obs.append([float(row['prey']), float(row['predator'])])

    with open('/app/data/metadata.toml', 'rb') as f:
        meta = tomllib.load(f)

    return (
        np.array(times),
        np.array(y_obs),
        np.array(meta['initial_conditions']['y0']),
        np.array(meta['initial_guess']['p_init']),
    )


T_EVAL, Y_DATA, Y0_ARR, P_INIT = _load_observations()
TRUE_P = np.array(TRUE_PARAMS)


def _compute_loss(params):
    """L2 loss between ODE solution and observations."""
    sol = solve_ivp(
        lambda t, u: lotka_volterra(t, u, params),
        [T_EVAL[0], T_EVAL[-1]], Y0_ARR,
        t_eval=T_EVAL, rtol=1e-10, atol=1e-12, method='RK45',
    )
    return float(np.sum((sol.y.T - Y_DATA) ** 2))


def _fd_gradient(params, h=1e-5):
    """Central finite-difference gradient."""
    params = np.asarray(params, dtype=float)
    grad = np.zeros(len(params))
    for j in range(len(params)):
        pp = params.copy(); pp[j] += h
        pm = params.copy(); pm[j] -= h
        grad[j] = (_compute_loss(pp) - _compute_loss(pm)) / (2.0 * h)
    return grad


# ---------------------------------------------------------------------------
# Test gradient at initial guess parameters
# ---------------------------------------------------------------------------
class TestGradientAtInitialParams:
    def test_gradient_vs_fd(self):
        """Gradient at initial guess must match central finite differences."""
        from estimator import compute_gradient
        grad = np.asarray(compute_gradient(
            P_INIT.copy(), Y0_ARR.copy(), T_EVAL.copy(), Y_DATA.copy()))
        grad_fd = _fd_gradient(P_INIT)
        rel_err = np.abs(grad - grad_fd) / (np.abs(grad_fd) + 1e-10)
        assert np.all(rel_err < 0.01), (
            f"Gradient vs FD relative error too large: {rel_err}"
        )


# ---------------------------------------------------------------------------
# Test gradient at true parameters
# ---------------------------------------------------------------------------
class TestGradientAtTrueParams:
    def test_gradient_vs_fd(self):
        """Gradient at true params must match central finite differences."""
        from estimator import compute_gradient
        grad = np.asarray(compute_gradient(
            TRUE_P.copy(), Y0_ARR.copy(), T_EVAL.copy(), Y_DATA.copy()))
        grad_fd = _fd_gradient(TRUE_P)
        for j in range(4):
            if abs(grad_fd[j]) > 0.01:
                assert abs(grad[j] - grad_fd[j]) / abs(grad_fd[j]) < 0.01, (
                    f"Component {j}: computed={grad[j]}, fd={grad_fd[j]}"
                )
            else:
                assert abs(grad[j] - grad_fd[j]) < 0.001


# ---------------------------------------------------------------------------
# Test parameter recovery
# ---------------------------------------------------------------------------
class TestParameterRecovery:
    def test_recover_parameters(self):
        """Optimizer must recover true parameters within 10% rel error."""
        from estimator import estimate_parameters
        p_est = np.asarray(estimate_parameters(
            Y_DATA.copy(), T_EVAL.copy(), Y0_ARR.copy(), P_INIT.copy()))
        rel_err = np.abs((p_est - TRUE_P) / TRUE_P)
        assert np.all(rel_err < 0.1), (
            f"Parameter recovery error: {rel_err}, estimated: {p_est}"
        )

    def test_loss_reduction(self):
        """Estimated parameters must reduce loss by at least 100x."""
        from estimator import estimate_parameters
        p_est = np.asarray(estimate_parameters(
            Y_DATA.copy(), T_EVAL.copy(), Y0_ARR.copy(), P_INIT.copy()))
        loss_init = _compute_loss(P_INIT)
        loss_est = _compute_loss(p_est)
        assert loss_est < loss_init * 0.01, (
            f"Loss not reduced enough: init={loss_init:.4f}, est={loss_est:.4f}"
        )


# ---------------------------------------------------------------------------
# Test output files
# ---------------------------------------------------------------------------
class TestOutputFiles:
    def test_parameters_json(self):
        """parameters.json must exist with correct schema and accurate params."""
        with open('/app/results/parameters.json') as f:
            d = json.load(f)
        assert 'recovered_params' in d, "Missing 'recovered_params' key"
        assert 'relative_errors' in d, "Missing 'relative_errors' key"
        assert 'converged' in d, "Missing 'converged' key"
        p_est = np.array(d['recovered_params'])
        assert len(p_est) == 4, f"Expected 4 params, got {len(p_est)}"
        rel_err = np.abs((p_est - TRUE_P) / TRUE_P)
        assert np.all(rel_err < 0.1), (
            f"Parameters in JSON inaccurate: rel_err={rel_err}"
        )

    def test_trajectory_csv(self):
        """trajectory.csv must exist with correct header format."""
        with open('/app/results/trajectory.csv') as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = list(reader)
        assert header[0].strip().lower() in ('t', 'time'), (
            f"First column must be 't' or 'time', got '{header[0]}'"
        )
        assert len(header) >= 3, (
            f"Need at least 3 columns (time + 2 states), got {len(header)}"
        )
        assert len(rows) > 0, "trajectory.csv has no data rows"

    def test_diagnostics_json(self):
        """diagnostics.json must exist with required fields."""
        with open('/app/results/diagnostics.json') as f:
            d = json.load(f)
        assert 'solver_method' in d, "Missing 'solver_method'"
        assert isinstance(d['solver_method'], str), "solver_method must be string"
        assert 'num_function_evaluations' in d, "Missing 'num_function_evaluations'"
        assert isinstance(d['num_function_evaluations'], int), (
            "num_function_evaluations must be integer"
        )
        assert 'final_loss' in d, "Missing 'final_loss'"
        assert isinstance(d['final_loss'], (int, float)), (
            "final_loss must be numeric"
        )
