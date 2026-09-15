#!/usr/bin/env python3
"""
Generalized Polynomial Chaos Expansion solver for nuclear thermal-hydraulic UQ.

Maps input distributions to orthogonal polynomial bases via the Wiener-Askey scheme,
computes PCE coefficients via spectral projection on a tensor-product Gauss quadrature
grid, and extracts statistics and Sobol sensitivity indices from the coefficients.
"""
import json
import math
import sys
from itertools import product as iproduct

import numpy as np

sys.path.insert(0, "/app")
from model import evaluate


# ---------------------------------------------------------------------------
# Quadrature
# ---------------------------------------------------------------------------

def gauss_legendre_prob(n):
    """Gauss-Legendre points on [-1,1] with probability weights (density = 1/2)."""
    pts, wts = np.polynomial.legendre.leggauss(n)
    return pts, wts / 2.0


def gauss_hermite_prob(n):
    """Gauss-Hermite (probabilist) points with probability weights (density = N(0,1))."""
    pts, wts = np.polynomial.hermite_e.hermegauss(n)
    return pts, wts / np.sqrt(2.0 * np.pi)


# ---------------------------------------------------------------------------
# Orthogonal polynomial evaluation
# ---------------------------------------------------------------------------

def eval_legendre(degree, x):
    """Evaluate Legendre polynomial P_n(x) using numpy coefficient representation."""
    c = np.zeros(degree + 1)
    c[degree] = 1.0
    return float(np.polynomial.legendre.legval(x, c))


def eval_hermite_e(degree, x):
    """Evaluate probabilist Hermite polynomial He_n(x)."""
    c = np.zeros(degree + 1)
    c[degree] = 1.0
    return float(np.polynomial.hermite_e.hermeval(x, c))


# ---------------------------------------------------------------------------
# Normalization factors  E[Psi_n^2]
# ---------------------------------------------------------------------------

def norm_legendre(degree):
    """E[P_n^2] under Uniform(-1,1) = 1/(2n+1)."""
    return 1.0 / (2 * degree + 1)


def norm_hermite(degree):
    """E[He_n^2] under N(0,1) = n!."""
    return float(math.factorial(degree))


# ---------------------------------------------------------------------------
# Main solver
# ---------------------------------------------------------------------------

def solve():
    with open("/app/config.json", "r") as f:
        config = json.load(f)

    inputs = config["inputs"]
    outputs = config["outputs"]
    pce_cfg = config["pce"]

    d = len(inputs)
    p = pce_cfg["polynomial_degree"]
    n_q = pce_cfg["points_per_dim"]

    # Per-dimension setup
    quad_pts = []
    quad_wts = []
    poly_fn = []
    norm_fn = []
    phys_transform = []

    for inp in inputs:
        dtype = inp["distribution"]
        par = inp["params"]

        if dtype == "uniform":
            a, b = par["a"], par["b"]
            pts, wts = gauss_legendre_prob(n_q)
            quad_pts.append(pts)
            quad_wts.append(wts)
            poly_fn.append(eval_legendre)
            norm_fn.append(norm_legendre)
            phys_transform.append(lambda xi, _a=a, _b=b: (_b - _a) / 2.0 * xi + (_a + _b) / 2.0)
        elif dtype == "normal":
            mu, sigma = par["mu"], par["sigma"]
            pts, wts = gauss_hermite_prob(n_q)
            quad_pts.append(pts)
            quad_wts.append(wts)
            poly_fn.append(eval_hermite_e)
            norm_fn.append(norm_hermite)
            phys_transform.append(lambda xi, _m=mu, _s=sigma: _s * xi + _m)
        else:
            raise ValueError(f"Unsupported distribution: {dtype}")

    # Multi-index set {alpha : |alpha| <= p}
    multi_indices = sorted(
        (alpha for alpha in iproduct(range(p + 1), repeat=d) if sum(alpha) <= p),
        key=lambda a: (sum(a), a),
    )
    n_terms = len(multi_indices)

    # Tensor-product quadrature grid
    grid = list(iproduct(*[range(n_q) for _ in range(d)]))
    n_grid = len(grid)
    n_out = len(outputs)

    # Evaluate model at every quadrature point
    model_vals = np.empty((n_grid, n_out))
    for k, gidx in enumerate(grid):
        x_phys = np.array([phys_transform[i](quad_pts[i][gidx[i]]) for i in range(d)])
        model_vals[k, :] = evaluate(x_phys)

    # Pre-compute basis values and weights at grid points
    # basis_vals[j, k] = Psi_{alpha_j}(xi_k)
    # weight_vals[k]   = product of per-dim probability weights
    basis_vals = np.empty((n_terms, n_grid))
    weight_vals = np.empty(n_grid)

    for k, gidx in enumerate(grid):
        weight_vals[k] = np.prod([quad_wts[i][gidx[i]] for i in range(d)])
        for j, alpha in enumerate(multi_indices):
            basis_vals[j, k] = np.prod(
                [poly_fn[i](alpha[i], quad_pts[i][gidx[i]]) for i in range(d)]
            )

    # Normalization gamma[j] = prod_i E[Psi_{alpha_i}^2]
    gamma = np.array(
        [np.prod([norm_fn[i](alpha[i]) for i in range(d)]) for alpha in multi_indices]
    )

    # PCE coefficients: c_alpha = E[f Psi_alpha] / gamma_alpha
    #   E[f Psi_alpha] ~= sum_k  model_vals[k] * basis_vals[j,k] * weight_vals[k]
    pce_coeffs = np.empty((n_terms, n_out))
    for j in range(n_terms):
        weighted_basis = basis_vals[j, :] * weight_vals  # (n_grid,)
        for o in range(n_out):
            pce_coeffs[j, o] = np.dot(model_vals[:, o], weighted_basis) / gamma[j]

    # ------------------------------------------------------------------
    # Extract statistics and Sobol indices
    # ------------------------------------------------------------------
    results = {"statistics": {}, "sobol_indices": {}}

    for o_idx, out in enumerate(outputs):
        oname = out["name"]
        c = pce_coeffs[:, o_idx]

        mean_val = float(c[0])
        var_val = float(np.sum(c[1:] ** 2 * gamma[1:]))
        std_val = float(np.sqrt(var_val))

        results["statistics"][oname] = {
            "mean": mean_val,
            "variance": var_val,
            "std": std_val,
        }

        first_order = {}
        total_order = {}

        for i, inp in enumerate(inputs):
            iname = inp["name"]

            # First-order: alpha_i >= 1 and alpha_j == 0 for all j != i
            s1_var = 0.0
            st_var = 0.0
            for j, alpha in enumerate(multi_indices):
                if j == 0:
                    continue
                if alpha[i] >= 1:
                    contrib = c[j] ** 2 * gamma[j]
                    st_var += contrib
                    if all(alpha[k] == 0 for k in range(d) if k != i):
                        s1_var += contrib

            first_order[iname] = float(s1_var / var_val) if var_val > 0 else 0.0
            total_order[iname] = float(st_var / var_val) if var_val > 0 else 0.0

        results["sobol_indices"][oname] = {
            "first_order": first_order,
            "total_order": total_order,
        }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    # Print summary
    for oname in results["statistics"]:
        s = results["statistics"][oname]
        print(f"{oname}: mean={s['mean']:.4f}, std={s['std']:.4f}")
        si = results["sobol_indices"][oname]
        print(f"  S1: {si['first_order']}")
        print(f"  ST: {si['total_order']}")


if __name__ == "__main__":
    solve()
