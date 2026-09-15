"""Analytical gradient computation and parameter estimation for Lotka-Volterra.

"""
import csv
import sys
import tomllib

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import minimize

sys.path.insert(0, '/app')
from system import lotka_volterra


def _jac_u(u, params):
    """Jacobian df/du of the Lotka-Volterra system."""
    x, y = u[0], u[1]
    alpha, beta, gamma, delta = params[0], params[1], params[2], params[3]
    return np.array([
        [alpha - beta * y, -beta * x],
        [delta * y, delta * x - gamma],
    ])


def _jac_p(u, params):
    """Jacobian df/dp of the Lotka-Volterra system."""
    x, y = u[0], u[1]
    return np.array([
        [x, -x * y, 0.0, 0.0],
        [0.0, 0.0, -y, x * y],
    ])


def _solve_fwd(params, y0, t_span, t_eval=None):
    """Solve ODE with high accuracy."""
    sol = solve_ivp(
        lambda t, u: np.array(lotka_volterra(t, u, params)),
        t_span, y0, t_eval=t_eval,
        rtol=1e-10, atol=1e-12, method='RK45',
    )
    return sol


def _compute_loss(params, y0, t_eval, y_data):
    """L2 loss between ODE trajectory and observed data."""
    sol = _solve_fwd(params, y0, [t_eval[0], t_eval[-1]], t_eval=t_eval)
    return float(np.sum((sol.y.T - y_data) ** 2))


def compute_gradient(params, y0, t_eval, y_data):
    """Compute dL/dp analytically via forward sensitivity equations.

    Augments the ODE with the sensitivity matrix S = du/dp,
    then accumulates the gradient from sensitivities at observation times.
    """
    params = np.asarray(params, dtype=float)
    y0 = np.asarray(y0, dtype=float)
    t_eval = np.asarray(t_eval, dtype=float)
    y_data = np.asarray(y_data, dtype=float)

    n_s = len(y0)
    n_p = len(params)

    def augmented_rhs(t, z):
        u = z[:n_s]
        S = z[n_s:].reshape(n_s, n_p)
        f_val = np.array(lotka_volterra(t, u, params))
        Ju = _jac_u(u, params)
        Jp = _jac_p(u, params)
        dS = Ju @ S + Jp
        return np.concatenate([f_val, dS.ravel()])

    z0 = np.zeros(n_s + n_s * n_p)
    z0[:n_s] = y0

    sol = solve_ivp(
        augmented_rhs, [t_eval[0], t_eval[-1]], z0,
        t_eval=t_eval, rtol=1e-10, atol=1e-12, method='RK45',
    )

    grad = np.zeros(n_p)
    for i in range(len(t_eval)):
        u_i = sol.y[:n_s, i]
        S_i = sol.y[n_s:, i].reshape(n_s, n_p)
        residual = u_i - y_data[i]
        grad += 2.0 * S_i.T @ residual

    return grad


def estimate_parameters(y_data, t_eval, y0, p_init):
    """Recover ODE parameters via gradient-based optimization."""
    y_data = np.asarray(y_data, dtype=float)
    t_eval = np.asarray(t_eval, dtype=float)
    y0 = np.asarray(y0, dtype=float)
    p_init = np.asarray(p_init, dtype=float)

    def objective(p):
        p = np.asarray(p, dtype=float)
        loss = _compute_loss(p, y0, t_eval, y_data)
        grad = compute_gradient(p, y0, t_eval, y_data)
        return loss, grad

    result = minimize(
        objective, p_init, jac=True,
        method='L-BFGS-B',
        bounds=[(1e-6, None)] * len(p_init),
        options={'maxiter': 200, 'ftol': 1e-15},
    )

    return result.x


def load_pipeline_data():
    """Load data from the pipeline's CSV and TOML files."""
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
