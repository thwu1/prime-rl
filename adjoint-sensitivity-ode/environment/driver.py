"""Parameter estimation driver for Lotka-Volterra system.

WARNING: This script was a work-in-progress and contains bugs.
It does not produce correct results.
"""
import json
import numpy as np
from scipy.integrate import solve_ivp
import sys
sys.path.insert(0, '/app')
from system import lotka_volterra, TRUE_PARAMS


def load_data():
    """Load observation data."""
    with open('/app/data.json') as f:
        d = json.load(f)
    return np.array(d['t_eval']), np.array(d['y_data'])


def simulate(params, y0, t_span, t_eval):
    """Simulate the ODE system."""
    sol = solve_ivp(
        lambda t, u: lotka_volterra(t, u, params),
        t_span, y0, t_eval=t_eval,
        method='RK23', rtol=1e-3, atol=1e-3,
    )
    return sol


def compute_gradient(params, y0, t_eval, y_data, h=1e-5):
    """Compute gradient of L2 loss via finite differences."""
    params = np.asarray(params, dtype=float)
    grad = np.zeros(len(params))
    loss0 = np.sum(
        (simulate(params, y0, [t_eval[0], t_eval[-1]], t_eval).y.T - y_data) ** 2
    )
    for j in range(len(params)):
        p_h = params.copy()
        p_h[j] += h
        loss_h = np.sum(
            (simulate(p_h, y0, [t_eval[0], t_eval[-1]], t_eval).y.T - y_data) ** 2
        )
        grad[j] = (loss_h - loss0) / h
    return grad


def estimate_parameters(y_data, t_eval, y0, p_init):
    """Gradient descent parameter estimation."""
    params = np.array(p_init, dtype=float)
    learning_rate = 0.01
    for iteration in range(50):
        grad = compute_gradient(params, y0, t_eval, y_data)
        params = params - learning_rate * grad
        if iteration % 10 == 0:
            loss = np.sum(
                (simulate(params, y0, [t_eval[0], t_eval[-1]], t_eval).y.T - y_data) ** 2
            )
            print(f"  Iteration {iteration}: loss = {loss:.4f}")
    return params


if __name__ == '__main__':
    try:
        t_eval, y_data = load_data()
    except FileNotFoundError:
        print("Error: Could not load observation data")
        sys.exit(1)

    y0 = np.array([1.0, 1.0])
    p_init = np.array([1.2, 0.8, 2.8, 0.8])
    p_est = estimate_parameters(y_data, t_eval, y0, p_init)
    print(f"Estimated: {p_est}")
    print(f"True:      {TRUE_PARAMS}")
