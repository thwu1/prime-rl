#!/usr/bin/env python3
"""
Solution for Cantilever Beam RBDO with Dakota tooling.
- Writes Dakota input file for FORM reliability analysis
- Uses NLopt LD_SLSQP for outer RBDO optimization
- Uses HL-RF FORM for inner reliability constraint evaluation
- Runs Monte Carlo validation
"""

import numpy as np
import nlopt
from scipy.stats import norm
import json
import csv
import os

# ============================================================
# Problem constants from problem.yaml
# ============================================================
L = 100.0
D0 = 2.2535
MU = np.array([40000.0, 29.0e6, 500.0, 1000.0])
SIGMA = np.array([2000.0, 1.45e6, 100.0, 100.0])
TARGET_BETA = 3.0


# ============================================================
# Structural analysis functions
# ============================================================

def compute_stress(w, t, X, Y):
    return 600.0 * Y / (w * t**2) + 600.0 * X / (w**2 * t)


def compute_disp_ratio(w, t, E, X, Y):
    S = np.sqrt((Y / t**2)**2 + (X / w**2)**2)
    return 4.0 * L**3 * S / (E * w * t * D0)


# ============================================================
# Limit state functions and gradients in standard normal space
# ============================================================

def g_stress(w, t, u):
    R = MU[0] + SIGMA[0] * u[0]
    X = MU[2] + SIGMA[2] * u[2]
    Y = MU[3] + SIGMA[3] * u[3]
    return 1.0 - compute_stress(w, t, X, Y) / R


def grad_g_stress(w, t, u):
    R = MU[0] + SIGMA[0] * u[0]
    X = MU[2] + SIGMA[2] * u[2]
    Y = MU[3] + SIGMA[3] * u[3]
    s = compute_stress(w, t, X, Y)
    return np.array([
        (s / R**2) * SIGMA[0],
        0.0,
        (-600.0 / (w**2 * t * R)) * SIGMA[2],
        (-600.0 / (w * t**2 * R)) * SIGMA[3],
    ])


def g_disp(w, t, u):
    E = MU[1] + SIGMA[1] * u[1]
    X = MU[2] + SIGMA[2] * u[2]
    Y = MU[3] + SIGMA[3] * u[3]
    return 1.0 - compute_disp_ratio(w, t, E, X, Y)


def grad_g_disp(w, t, u):
    E = MU[1] + SIGMA[1] * u[1]
    X = MU[2] + SIGMA[2] * u[2]
    Y = MU[3] + SIGMA[3] * u[3]
    S = np.sqrt((Y / t**2)**2 + (X / w**2)**2)
    D = 4.0 * L**3 * S / (E * w * t)
    C = 4.0 * L**3 / (E * w * t)
    return np.array([
        0.0,
        (D / (E * D0)) * SIGMA[1],
        (-C * X / (w**4 * S * D0)) * SIGMA[2],
        (-C * Y / (t**4 * S * D0)) * SIGMA[3],
    ])


# ============================================================
# HL-RF FORM algorithm
# ============================================================

def hlrf_form(g_func, grad_func, n_vars, max_iter=200, tol=1e-8):
    u = np.zeros(n_vars)
    for _ in range(max_iter):
        g = g_func(u)
        dg = grad_func(u)
        norm_dg_sq = np.dot(dg, dg)
        if norm_dg_sq < 1e-30:
            break
        u_new = (np.dot(dg, u) - g) / norm_dg_sq * dg
        du = np.linalg.norm(u_new - u)
        u = u_new
        if du < tol and abs(g_func(u)) < tol:
            break
    return np.linalg.norm(u), u


def beta_stress_eval(w, t):
    return hlrf_form(
        lambda u: g_stress(w, t, u),
        lambda u: grad_g_stress(w, t, u), 4)


def beta_disp_eval(w, t):
    return hlrf_form(
        lambda u: g_disp(w, t, u),
        lambda u: grad_g_disp(w, t, u), 4)


# ============================================================
# FORM validation on linear test case
# ============================================================

def form_validation():
    def g_lin(u):
        return 5.0 + 0.6 * u[0] - 0.8 * u[1]
    def grad_lin(u):
        return np.array([0.6, -0.8])
    beta, mpp = hlrf_form(g_lin, grad_lin, n_vars=2)
    return {"beta": float(beta), "mpp": [float(mpp[0]), float(mpp[1])]}


# ============================================================
# Write Dakota input file
# ============================================================

def write_dakota_input():
    content = """\
environment
  tabular_data
    tabular_data_file = 'dakota_cantilever_tabular.dat'

method
  local_reliability
    mpp_search no_approx
    response_levels = 0.0 0.0

variables
  continuous_design = 2
    initial_point    4.0          4.0
    upper_bounds    10.0         10.0
    lower_bounds     1.0          1.0
    descriptors     'w' 't'
  normal_uncertain = 4
    means           40000.  29.E+6  500.  1000.
    std_deviations   2000.  1.45E+6  100.  100.
    descriptors     'R'  'E'  'X'  'Y'

interface
  analysis_drivers = 'python3 /app/cantilever_driver.py'
    fork
      parameters_file = 'params.in'
      results_file    = 'results.out'

responses
  response_functions = 2
    descriptors = 'stress_con' 'disp_con'
  analytic_gradients
  no_hessians
"""
    with open("/app/dakota_cantilever.in", "w") as f:
        f.write(content)


# ============================================================
# RBDO optimization using NLopt
# ============================================================

def run_rbdo_nlopt():
    convergence = []
    beta_cache = {}
    prev_x = [None, None]

    def get_betas(w, t):
        key = (round(w, 8), round(t, 8))
        if key not in beta_cache:
            bs, _ = beta_stress_eval(w, t)
            bd, _ = beta_disp_eval(w, t)
            beta_cache[key] = (float(bs), float(bd))
        return beta_cache[key]

    def objective(x, grad):
        w, t = float(x[0]), float(x[1])
        if w != prev_x[0] or t != prev_x[1]:
            bs, bd = get_betas(w, t)
            convergence.append({
                "iteration": len(convergence),
                "w": w, "t": t, "area": w * t,
                "beta_stress": bs, "beta_displacement": bd,
            })
            prev_x[0] = w
            prev_x[1] = t
        if grad.size > 0:
            grad[0] = x[1]
            grad[1] = x[0]
        return x[0] * x[1]

    def stress_constraint(x, grad):
        """NLopt convention: c(x) <= 0. Want beta >= target, so target - beta <= 0."""
        w, t = float(x[0]), float(x[1])
        bs, _ = get_betas(w, t)
        if grad.size > 0:
            h = 1e-5
            bsw, _ = beta_stress_eval(w + h, t)
            bst, _ = beta_stress_eval(w, t + h)
            grad[0] = -(float(bsw) - bs) / h
            grad[1] = -(float(bst) - bs) / h
        return TARGET_BETA - bs

    def disp_constraint(x, grad):
        """NLopt convention: c(x) <= 0. Want beta >= target, so target - beta <= 0."""
        w, t = float(x[0]), float(x[1])
        _, bd = get_betas(w, t)
        if grad.size > 0:
            h = 1e-5
            bdw, _ = beta_disp_eval(w + h, t)
            bdt, _ = beta_disp_eval(w, t + h)
            grad[0] = -(float(bdw) - bd) / h
            grad[1] = -(float(bdt) - bd) / h
        return TARGET_BETA - bd

    opt = nlopt.opt(nlopt.LD_SLSQP, 2)
    opt.set_min_objective(objective)
    opt.set_lower_bounds([1.0, 1.0])
    opt.set_upper_bounds([10.0, 10.0])
    opt.add_inequality_constraint(stress_constraint, 1e-8)
    opt.add_inequality_constraint(disp_constraint, 1e-8)
    opt.set_xtol_rel(1e-6)
    opt.set_maxeval(200)

    xopt = opt.optimize([4.0, 4.0])

    w_opt, t_opt = float(xopt[0]), float(xopt[1])
    bs_final, _ = beta_stress_eval(w_opt, t_opt)
    bd_final, _ = beta_disp_eval(w_opt, t_opt)

    optimal = {
        "w": w_opt,
        "t": t_opt,
        "area": w_opt * t_opt,
        "beta_stress": float(bs_final),
        "beta_displacement": float(bd_final),
        "algorithm": "LD_SLSQP",
    }
    return optimal, convergence


# ============================================================
# Monte Carlo validation
# ============================================================

def monte_carlo_validation(w, t, n_samples=500000, seed=42):
    rng = np.random.default_rng(seed)
    R = rng.normal(MU[0], SIGMA[0], n_samples)
    E = rng.normal(MU[1], SIGMA[1], n_samples)
    X = rng.normal(MU[2], SIGMA[2], n_samples)
    Y = rng.normal(MU[3], SIGMA[3], n_samples)

    stress = compute_stress(w, t, X, Y)
    disp_ratio = compute_disp_ratio(w, t, E, X, Y)

    pf_s = float(np.mean(stress >= R))
    pf_d = float(np.mean(disp_ratio >= 1.0))

    beta_s_mc = float(-norm.ppf(pf_s)) if pf_s > 0 else 10.0
    beta_d_mc = float(-norm.ppf(pf_d)) if pf_d > 0 else 10.0

    return {
        "n_samples": n_samples,
        "pf_stress": pf_s,
        "pf_displacement": pf_d,
        "beta_stress_mc": beta_s_mc,
        "beta_displacement_mc": beta_d_mc,
    }


# ============================================================
# Main
# ============================================================

def main():
    os.makedirs("/app/results", exist_ok=True)

    # 1. Write Dakota input file
    print("=== Writing Dakota input file ===")
    write_dakota_input()

    # 2. FORM validation on linear test case
    print("=== FORM Validation ===")
    fv = form_validation()
    with open("/app/results/form_validation.json", "w") as f:
        json.dump(fv, f, indent=2)
    print(f"Beta: {fv['beta']:.6f} (expected 5.0)")
    print(f"MPP:  {fv['mpp']} (expected [-3.0, 4.0])")

    # 3. RBDO with NLopt
    print("\n=== RBDO Optimization (NLopt LD_SLSQP) ===")
    optimal, convergence = run_rbdo_nlopt()
    with open("/app/results/optimal_design.json", "w") as f:
        json.dump(optimal, f, indent=2)
    print(f"Optimal: w={optimal['w']:.4f}, t={optimal['t']:.4f}")
    print(f"Area:    {optimal['area']:.4f}")
    print(f"Beta_s:  {optimal['beta_stress']:.4f}")
    print(f"Beta_d:  {optimal['beta_displacement']:.4f}")
    print(f"Algorithm: {optimal['algorithm']}")

    # 4. Convergence history
    with open("/app/results/convergence.csv", "w", newline="") as f:
        writer = csv.DictWriter(f,
            fieldnames=["iteration", "w", "t", "area",
                        "beta_stress", "beta_displacement"])
        writer.writeheader()
        writer.writerows(convergence)
    print(f"Recorded {len(convergence)} iterations")

    # 5. Monte Carlo validation
    print("\n=== Monte Carlo Validation ===")
    mc = monte_carlo_validation(optimal["w"], optimal["t"])
    with open("/app/results/monte_carlo.json", "w") as f:
        json.dump(mc, f, indent=2)
    print(f"Samples:   {mc['n_samples']}")
    print(f"pf_stress: {mc['pf_stress']:.6f}")
    print(f"pf_disp:   {mc['pf_displacement']:.6f}")

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
