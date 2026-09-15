
"""
Polynomial Chaos Expansion (PCE) pipeline for cantilever beam UQ.

Implements non-intrusive spectral projection using Gauss-Hermite quadrature
with probabilists' Hermite polynomial basis and total-degree multi-index
truncation. Computes statistical moments, Sobol sensitivity indices, and
FOSM reliability analysis for stress and displacement limit states.
"""

import json
import math
from itertools import product

import numpy as np
from scipy.special import eval_hermitenorm, roots_hermitenorm
from scipy.stats import norm


def load_config(path="/app/problem_spec.json"):
    with open(path) as f:
        return json.load(f)


def gauss_hermite_rule(n_points):
    """
    Generate Gauss-Hermite quadrature for standard normal expectation.

    scipy's roots_hermitenorm gives weights for int f(x) exp(-x^2/2) dx.
    Dividing by sqrt(2*pi) gives weights for E[f(xi)] where xi ~ N(0,1).
    """
    nodes, weights = roots_hermitenorm(n_points)
    weights = weights / np.sqrt(2.0 * np.pi)
    return nodes, weights


def tensor_product_grid(rules_1d):
    """
    Build d-dimensional tensor product quadrature from 1D rules.

    Parameters
    ----------
    rules_1d : list of (nodes, weights) tuples for each dimension

    Returns
    -------
    nodes : ndarray of shape (N, d) - quadrature nodes in standard normal space
    weights : ndarray of shape (N,) - quadrature weights for E[f(xi)]
    """
    grids = [r[0] for r in rules_1d]
    wts = [r[1] for r in rules_1d]
    mesh = np.array(list(product(*grids)))
    w_combos = list(product(*wts))
    w = np.array([np.prod(ww) for ww in w_combos])
    return mesh, w


def multi_index_set(dim, max_degree):
    """Generate all multi-indices alpha with |alpha|_1 <= max_degree."""
    if dim == 1:
        return [(i,) for i in range(max_degree + 1)]
    result = []
    for i in range(max_degree + 1):
        for rest in multi_index_set(dim - 1, max_degree - i):
            result.append((i,) + rest)
    return result


def eval_normalized_hermite_1d(n, x):
    """
    Evaluate normalized probabilists' Hermite polynomial.

    phi_n(x) = He_n(x) / sqrt(n!)

    where He_n is the probabilists' Hermite polynomial satisfying:
    E[He_m(xi) * He_n(xi)] = n! * delta_{mn}  for xi ~ N(0,1)

    The normalized basis satisfies E[phi_m * phi_n] = delta_{mn}.
    """
    return float(eval_hermitenorm(int(n), x)) / math.sqrt(math.factorial(int(n)))


def eval_multivariate_basis(alpha, xi):
    """
    Evaluate normalized multivariate Hermite basis function.

    Phi_alpha(xi) = prod_i phi_{alpha_i}(xi_i)

    Orthonormality: E[Phi_alpha * Phi_beta] = delta_{alpha, beta}
    """
    val = 1.0
    for i, a in enumerate(alpha):
        val *= eval_normalized_hermite_1d(a, xi[i])
    return val


def spectral_projection(nodes, weights, f_vals, alphas):
    """
    Compute PCE coefficients via spectral projection (Galerkin).

    c_alpha = E[f(xi) * Phi_alpha(xi)]
            ~ sum_k w_k * f(xi_k) * Phi_alpha(xi_k)
    """
    n_nodes = len(nodes)
    n_alpha = len(alphas)

    # Precompute basis values at all quadrature nodes
    basis_matrix = np.zeros((n_nodes, n_alpha))
    for k in range(n_nodes):
        for j, alpha in enumerate(alphas):
            basis_matrix[k, j] = eval_multivariate_basis(alpha, nodes[k])

    # Projection: c_j = sum_k w_k * f_k * Phi_j(xi_k)
    coeffs = np.zeros(n_alpha)
    for j in range(n_alpha):
        coeffs[j] = np.dot(weights * f_vals, basis_matrix[:, j])

    return coeffs


def sobol_indices_from_pce(coeffs, alphas, dim):
    """
    Compute first-order and total Sobol sensitivity indices from PCE.

    Total variance: D = sum_{alpha != 0} c_alpha^2

    First-order S_i: fraction of variance from terms where ONLY alpha_i > 0
      D_i = sum_{alpha: alpha_i > 0, alpha_j = 0 for j != i} c_alpha^2

    Total S_Ti: fraction of variance from ALL terms where alpha_i > 0
      D_Ti = sum_{alpha: alpha_i > 0} c_alpha^2
    """
    total_var = sum(c ** 2 for c, a in zip(coeffs, alphas) if sum(a) > 0)

    first_order = np.zeros(dim)
    total = np.zeros(dim)

    if total_var < 1e-30:
        return first_order, total

    for c, a in zip(coeffs, alphas):
        if sum(a) == 0:
            continue

        active_dims = [i for i in range(dim) if a[i] > 0]

        # Total index: any term involving variable i
        for i in active_dims:
            total[i] += c ** 2

        # First-order: terms involving ONLY one variable
        if len(active_dims) == 1:
            first_order[active_dims[0]] += c ** 2

    return first_order / total_var, total / total_var


def cantilever_evaluate(w, t, R, E, X, Y, L, D0):
    """Evaluate cantilever beam stress and displacement."""
    stress = 600.0 * Y / (w * t ** 2) + 600.0 * X / (w ** 2 * t)
    D1 = 4.0 * L ** 3 / (E * w * t)
    D2 = (Y / t ** 2) ** 2 + (X / w ** 2) ** 2
    displacement = D1 * np.sqrt(D2) / D0
    return stress, displacement


def main():
    config = load_config()

    # Design point
    w = config["design_point"]["w"]
    t = config["design_point"]["t"]

    # Beam parameters
    L = config["beam_parameters"]["L"]
    D0 = config["beam_parameters"]["D0"]

    # Uncertain variables (order: R, E, X, Y)
    var_names = ["R", "E", "X", "Y"]
    uv = config["uncertain_variables"]
    means = np.array([uv[v]["mean"] for v in var_names])
    stds = np.array([uv[v]["std"] for v in var_names])

    # PCE configuration
    total_deg = config["pce_config"]["total_degree"]
    dim = len(var_names)

    # Build tensor-product Gauss-Hermite quadrature
    # Use total_deg + 2 points per dimension for accurate integration
    # of polynomials up to degree 2*(total_deg+1)-1 = 2*total_deg+1
    n_q = total_deg + 2
    rule_1d = gauss_hermite_rule(n_q)
    nodes, weights = tensor_product_grid([rule_1d] * dim)
    n_points = len(nodes)

    # Generate total-degree multi-index set
    alphas = multi_index_set(dim, total_deg)

    # Evaluate cantilever and limit state functions at all quadrature nodes
    stress_vals = np.zeros(n_points)
    disp_vals = np.zeros(n_points)
    g_stress_vals = np.zeros(n_points)
    g_disp_vals = np.zeros(n_points)

    for k in range(n_points):
        xi = nodes[k]
        # Isoprobabilistic transform: physical = mean + std * xi
        phys = means + stds * xi
        R_k, E_k, X_k, Y_k = phys

        stress, displacement = cantilever_evaluate(w, t, R_k, E_k, X_k, Y_k, L, D0)

        stress_vals[k] = stress
        disp_vals[k] = displacement
        g_stress_vals[k] = stress - R_k  # limit state: stress > R
        g_disp_vals[k] = displacement - 1.0  # limit state: disp > 1

    # Compute PCE coefficients via spectral projection
    stress_coeffs = spectral_projection(nodes, weights, stress_vals, alphas)
    disp_coeffs = spectral_projection(nodes, weights, disp_vals, alphas)
    g_stress_coeffs = spectral_projection(nodes, weights, g_stress_vals, alphas)
    g_disp_coeffs = spectral_projection(nodes, weights, g_disp_vals, alphas)

    # Extract statistical moments from PCE
    stress_mean = float(stress_coeffs[0])
    stress_var = float(sum(c ** 2 for c, a in zip(stress_coeffs, alphas) if sum(a) > 0))
    stress_std = float(np.sqrt(stress_var))

    disp_mean = float(disp_coeffs[0])
    disp_var = float(sum(c ** 2 for c, a in zip(disp_coeffs, alphas) if sum(a) > 0))
    disp_std = float(np.sqrt(disp_var))

    # Sobol sensitivity indices from PCE ANOVA decomposition
    stress_s1, stress_st = sobol_indices_from_pce(stress_coeffs, alphas, dim)
    disp_s1, disp_st = sobol_indices_from_pce(disp_coeffs, alphas, dim)

    # FOSM reliability analysis for stress limit state: g = stress - R
    g_stress_mean = float(g_stress_coeffs[0])
    g_stress_var = float(
        sum(c ** 2 for c, a in zip(g_stress_coeffs, alphas) if sum(a) > 0)
    )
    g_stress_std = float(np.sqrt(g_stress_var))
    beta_stress = -g_stress_mean / g_stress_std
    pf_stress = float(norm.cdf(-beta_stress))

    # FOSM reliability analysis for displacement limit state: g = disp - 1
    g_disp_mean = float(g_disp_coeffs[0])
    g_disp_var = float(
        sum(c ** 2 for c, a in zip(g_disp_coeffs, alphas) if sum(a) > 0)
    )
    g_disp_std = float(np.sqrt(g_disp_var))
    beta_disp = -g_disp_mean / g_disp_std
    pf_disp = float(norm.cdf(-beta_disp))

    # Build output matching schema
    results = {
        "stress_mean": stress_mean,
        "stress_std": stress_std,
        "displacement_mean": disp_mean,
        "displacement_std": disp_std,
        "sobol_first_order": {
            "stress": {v: float(stress_s1[i]) for i, v in enumerate(var_names)},
            "displacement": {v: float(disp_s1[i]) for i, v in enumerate(var_names)},
        },
        "sobol_total": {
            "stress": {v: float(stress_st[i]) for i, v in enumerate(var_names)},
            "displacement": {v: float(disp_st[i]) for i, v in enumerate(var_names)},
        },
        "failure_stress": {
            "probability": pf_stress,
            "reliability_index": float(beta_stress),
        },
        "failure_displacement": {
            "probability": pf_disp,
            "reliability_index": float(beta_disp),
        },
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("UQ results written to /app/results.json")


if __name__ == "__main__":
    main()
