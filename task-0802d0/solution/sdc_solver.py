#!/usr/bin/env python3
"""
SDC convergence and stability analysis solver.

"""

import json
import numpy as np
from numpy.polynomial import legendre as L
from numpy.polynomial import polynomial as P
from scipy.optimize import minimize


def gauss_radau_iia_nodes(M):
    """Compute M Gauss-Radau IIa nodes on [0, 1].

    Nodes are roots of P_M(x) - P_{M-1}(x) on [-1,1], mapped to [0,1].
    """
    if M == 1:
        return np.array([1.0])

    # Build P_M and P_{M-1} in Legendre basis, convert to power basis
    c_M = np.zeros(M + 1)
    c_M[M] = 1.0
    c_M1 = np.zeros(M)
    c_M1[M - 1] = 1.0

    p_M = L.leg2poly(c_M)
    p_M1 = L.leg2poly(c_M1)

    # P_M(x) - P_{M-1}(x) in power basis
    p_M1_padded = np.zeros(len(p_M))
    p_M1_padded[:len(p_M1)] = p_M1
    diff_poly = p_M - p_M1_padded

    # np.roots expects coefficients in descending power order
    roots = np.roots(diff_poly[::-1])

    # Keep real roots in [-1, 1]
    real_mask = np.abs(np.imag(roots)) < 1e-10
    roots = np.real(roots[real_mask])
    roots = roots[(roots >= -1.0 - 1e-10) & (roots <= 1.0 + 1e-10)]
    roots = np.sort(roots)

    # Map to [0, 1]
    nodes = (roots + 1.0) / 2.0
    nodes[-1] = 1.0  # enforce exact right endpoint

    return nodes


def compute_Q_matrix(nodes):
    """Compute spectral integration matrix Q via Lagrange polynomial integration.

    Q_{ij} = integral from 0 to tau_i of l_j(s) ds
    """
    M = len(nodes)
    Q = np.zeros((M, M))

    for j in range(M):
        # Build l_j(s) in coefficient form (increasing powers)
        coefs = np.array([1.0])
        for k in range(M):
            if k == j:
                continue
            factor = np.array([-nodes[k], 1.0]) / (nodes[j] - nodes[k])
            coefs = P.polymul(coefs, factor)

        # Antiderivative
        anti = P.polyint(coefs)

        for i in range(M):
            Q[i, j] = P.polyval(nodes[i], anti) - P.polyval(0.0, anti)

    return Q


def backward_euler_preconditioner(nodes):
    """Construct backward-Euler preconditioner Q_delta.

    Q_delta_{m,j} = tau_j - tau_{j-1} for j <= m, else 0.
    """
    M = len(nodes)
    Q_delta = np.zeros((M, M))
    deltas = np.diff(np.concatenate(([0.0], nodes)))
    for i in range(M):
        for j in range(i + 1):
            Q_delta[i, j] = deltas[j]
    return Q_delta


def sdc_step(Q, Q_delta, z, u0, K):
    """One SDC time step: predictor + K correction sweeps.

    Returns the solution at the last collocation node.
    """
    M = Q.shape[0]
    I = np.eye(M)
    ones = np.ones(M)

    # Predictor: (I - z*Q_delta) U^0 = u0 * 1
    U = np.linalg.solve(I - z * Q_delta, u0 * ones)

    # K correction sweeps
    for _ in range(K):
        rhs = u0 * ones + z * (Q - Q_delta) @ U
        U = np.linalg.solve(I - z * Q_delta, rhs)

    return U[-1]


def convergence_study(M=3, K_values=range(1, 6)):
    """Convergence order study for u'(t) = -u(t), u(0) = 1, t in [0,1]."""
    N_values = [4, 8, 16, 32, 64]
    nodes = gauss_radau_iia_nodes(M)
    Q = compute_Q_matrix(nodes)
    Q_delta = backward_euler_preconditioner(nodes)
    exact = np.exp(-1.0)

    orders = {}
    for K in K_values:
        errors = []
        for N in N_values:
            dt = 1.0 / N
            z = -1.0 * dt
            u = 1.0
            for _ in range(N):
                u = sdc_step(Q, Q_delta, z, u, K)
            errors.append(abs(u - exact))

        # Richardson order from last two refinement levels
        if errors[-1] > 1e-15 and errors[-2] > 1e-15:
            order = np.log(errors[-2] / errors[-1]) / np.log(
                N_values[-1] / N_values[-2]
            )
        else:
            order = float('inf')

        orders[str(K)] = round(float(order), 6)

    return orders


def stability_function_value(Q, Q_delta, z, K):
    """Compute SDC stability function R(z) = last component of U^K with u0=1."""
    return sdc_step(Q, Q_delta, z, 1.0, K)


def optimize_diagonal_preconditioner(Q):
    """Find diagonal D = diag(d) minimizing rho(I - D^{-1} Q), d > 0."""
    M = Q.shape[0]
    I = np.eye(M)

    def objective(log_d):
        d = np.exp(log_d)
        D_inv = np.diag(1.0 / d)
        M_mat = I - D_inv @ Q
        eigvals = np.linalg.eigvals(M_mat)
        return float(max(abs(eigvals)))

    best_d = None
    best_rho = float('inf')

    np.random.seed(42)
    for trial in range(30):
        if trial == 0:
            x0 = np.log(np.abs(np.diag(Q)))
        elif trial < 5:
            x0 = np.log(np.abs(np.diag(Q))) + 0.3 * np.random.randn(M)
        else:
            x0 = np.log(np.abs(np.diag(Q))) + np.random.randn(M)

        result = minimize(
            objective, x0, method='Nelder-Mead',
            options={'xatol': 1e-12, 'fatol': 1e-12, 'maxiter': 10000,
                     'adaptive': True}
        )

        if result.fun < best_rho:
            best_rho = result.fun
            best_d = np.exp(result.x)

    return best_d, best_rho


def main():
    # 1. Compute nodes
    nodes_M3 = gauss_radau_iia_nodes(3)
    nodes_M5 = gauss_radau_iia_nodes(5)

    # 2. Compute Q matrix for M=3
    Q_M3 = compute_Q_matrix(nodes_M3)

    # 3. Convergence orders
    conv_orders = convergence_study(M=3)

    # 4. Stability function values for M=3, K=3
    Q_delta_M3 = backward_euler_preconditioner(nodes_M3)
    z_values = [-0.5, -1.0, -2.0, -5.0, -10.0]
    stab_R = {}
    for z in z_values:
        R = stability_function_value(Q_M3, Q_delta_M3, z, K=3)
        stab_R[str(z)] = float(R)

    # 5. Optimal diagonal preconditioner for M=3
    d_opt, rho_opt = optimize_diagonal_preconditioner(Q_M3)

    results = {
        "nodes_M3": nodes_M3.tolist(),
        "nodes_M5": nodes_M5.tolist(),
        "Q_M3": Q_M3.tolist(),
        "convergence_orders": conv_orders,
        "stability_R": stab_R,
        "optimal_diag_entries": d_opt.tolist(),
        "optimal_spectral_radius": float(rho_opt),
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
