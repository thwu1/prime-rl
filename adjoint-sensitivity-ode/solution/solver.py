#!/usr/bin/env python3
"""
Solve the ODE sensitivity analysis task by creating /app/sensitivity.py
with forward sensitivity, adjoint sensitivity, and parameter estimation.
"""
import textwrap

CODE = textwrap.dedent(r'''
import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import minimize
import sys
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


def _solve_ode(params, y0, t_span, t_eval=None, dense=False):
    """Solve the Lotka-Volterra ODE."""
    sol = solve_ivp(
        lambda t, u: np.array(lotka_volterra(t, u, params)),
        t_span, y0, t_eval=t_eval,
        rtol=1e-10, atol=1e-12, method='RK45',
        dense_output=dense,
    )
    return sol


def _compute_loss(params, y0, t_eval, y_data):
    """L2 loss between ODE trajectory and observed data."""
    sol = _solve_ode(params, y0, [t_eval[0], t_eval[-1]], t_eval=t_eval)
    return float(np.sum((sol.y.T - y_data) ** 2))


def forward_sensitivity_gradient(params, y0, t_eval, y_data):
    """Compute dL/dp via forward sensitivity equations.

    Augments the ODE with the sensitivity matrix S = du/dp,
    satisfying dS/dt = (df/du) S + df/dp, with S(0) = 0.
    The gradient is dL/dp = sum_i 2 * S(t_i)^T * (u(t_i) - y_data_i).
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


def adjoint_sensitivity_gradient(params, y0, t_eval, y_data):
    """Compute dL/dp via the continuous adjoint method.

    Solves the adjoint ODE backward in time with jump discontinuities
    at each observation point, accumulating the gradient integral.
    """
    params = np.asarray(params, dtype=float)
    y0 = np.asarray(y0, dtype=float)
    t_eval = np.asarray(t_eval, dtype=float)
    y_data = np.asarray(y_data, dtype=float)

    n_s = len(y0)
    n_p = len(params)

    # Forward solve with dense output for interpolation
    sol_fwd = _solve_ode(params, y0,
                         [t_eval[0], t_eval[-1]], dense=True)

    # Forward solution at observation times
    u_obs = np.array([sol_fwd.sol(t) for t in t_eval])

    # Initialize adjoint at t=T with the terminal observation jump
    lam = 2.0 * (u_obs[-1] - y_data[-1])
    grad = np.zeros(n_p)

    # Integrate backward through each observation interval
    for i in range(len(t_eval) - 1, 0, -1):
        t_start = float(t_eval[i])
        t_end = float(t_eval[i - 1])

        # Capture loop variables for the closure
        def backward_rhs(t, z, _sol=sol_fwd, _p=params):
            lam_loc = z[:n_s]
            u = _sol.sol(t)
            Ju = _jac_u(u, _p)
            Jp = _jac_p(u, _p)
            dlam = -Ju.T @ lam_loc
            dmu = Jp.T @ lam_loc
            return np.concatenate([dlam, dmu])

        z0_back = np.concatenate([lam, np.zeros(n_p)])
        sol_back = solve_ivp(
            backward_rhs, [t_start, t_end], z0_back,
            rtol=1e-10, atol=1e-12, method='RK45',
        )

        lam = sol_back.y[:n_s, -1]
        # Note the sign: integrating backward flips the integral sign
        grad -= sol_back.y[n_s:, -1]

        # Add jump discontinuity at t_{i-1}
        if i - 1 > 0:
            lam += 2.0 * (u_obs[i - 1] - y_data[i - 1])

    return grad


def estimate_parameters(y_data, t_eval, y0, p_init, method='adjoint'):
    """Recover ODE parameters via gradient-based optimization.

    Uses L-BFGS-B with gradients from the specified sensitivity method.
    """
    y_data = np.asarray(y_data, dtype=float)
    t_eval = np.asarray(t_eval, dtype=float)
    y0 = np.asarray(y0, dtype=float)
    p_init = np.asarray(p_init, dtype=float)

    if method == 'adjoint':
        grad_fn = adjoint_sensitivity_gradient
    else:
        grad_fn = forward_sensitivity_gradient

    def objective(p):
        p = np.asarray(p, dtype=float)
        loss = _compute_loss(p, y0, t_eval, y_data)
        grad = grad_fn(p, y0, t_eval, y_data)
        return loss, grad

    result = minimize(
        lambda p: objective(p), p_init, jac=True,
        method='L-BFGS-B',
        bounds=[(1e-6, None)] * len(p_init),
        options={'maxiter': 200, 'ftol': 1e-15},
    )

    return result.x
''').strip()

with open('/app/sensitivity.py', 'w') as f:
    f.write(CODE + '\n')

print("Created /app/sensitivity.py")

# Verify it works
import sys
sys.path.insert(0, '/app')
import numpy as np
from sensitivity import (
    forward_sensitivity_gradient,
    adjoint_sensitivity_gradient,
    estimate_parameters,
)
from system import load_data, TRUE_PARAMS

t_list, y_list, y0_list, pi_list = load_data()
t_eval = np.array(t_list)
y_data = np.array(y_list)
y0 = np.array(y0_list)
p_init = np.array(pi_list)
true_p = np.array(TRUE_PARAMS)

g_fwd = forward_sensitivity_gradient(p_init, y0, t_eval, y_data)
g_adj = adjoint_sensitivity_gradient(p_init, y0, t_eval, y_data)
print(f"Forward gradient:  {g_fwd}")
print(f"Adjoint gradient:  {g_adj}")

p_est = estimate_parameters(y_data, t_eval, y0, p_init, method='adjoint')
print(f"True params:      {true_p}")
print(f"Estimated params: {p_est}")
print(f"Relative error:   {np.abs((p_est - true_p) / true_p)}")
