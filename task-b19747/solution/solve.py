#!/usr/bin/env python3
"""
Bayesian posterior inference for stat_comp_benchmarks models.

- Eight Schools: Adaptive Metropolis-Hastings MCMC (Laplace fails due to
  heavy-tailed HalfCauchy prior causing MAP to diverge from posterior mean).
- GP Regression: Laplace approximation + Monte Carlo (works well for
  concentrated, approximately Gaussian posterior).
- SIR: Laplace approximation + Monte Carlo with ODE solves for each sample.
"""


import json
import os
import numpy as np
from scipy.optimize import minimize
from scipy.integrate import solve_ivp
from scipy.linalg import cholesky, solve_triangular
from scipy.special import gammaln

np.random.seed(42)


# ============================================================
# Utility: Hessian via central finite differences
# ============================================================

def compute_hessian(f, x, eps=1e-4):
    n = len(x)
    H = np.zeros((n, n))
    for i in range(n):
        for j in range(i, n):
            xpp = x.copy(); xpp[i] += eps; xpp[j] += eps
            xpm = x.copy(); xpm[i] += eps; xpm[j] -= eps
            xmp = x.copy(); xmp[i] -= eps; xmp[j] += eps
            xmm = x.copy(); xmm[i] -= eps; xmm[j] -= eps
            H[i, j] = (f(xpp) - f(xpm) - f(xmp) + f(xmm)) / (4 * eps * eps)
            H[j, i] = H[i, j]
    return H


# ============================================================
# Utility: Laplace approximation + MC sampling
# ============================================================

def laplace_sample(neg_log_post, x0, n_mc=100000, n_restarts=10):
    best = None
    for _ in range(n_restarts):
        x_init = x0 + 0.1 * np.random.randn(len(x0))
        try:
            res = minimize(neg_log_post, x_init, method='L-BFGS-B',
                           options={'maxiter': 30000, 'ftol': 1e-15, 'gtol': 1e-12})
            if best is None or res.fun < best.fun:
                best = res
        except Exception:
            continue
    if best is None:
        raise RuntimeError("Optimization failed")
    map_est = best.x
    print(f"  MAP neg-log-post = {best.fun:.6f}")

    H = compute_hessian(neg_log_post, map_est)
    eigvals, eigvecs = np.linalg.eigh(H)
    eigvals = np.maximum(eigvals, 1e-4)
    H = eigvecs @ np.diag(eigvals) @ eigvecs.T
    cov = np.linalg.inv(H)
    cov = 0.5 * (cov + cov.T)
    eigvals_c, eigvecs_c = np.linalg.eigh(cov)
    eigvals_c = np.maximum(eigvals_c, 1e-10)
    cov = eigvecs_c @ np.diag(eigvals_c) @ eigvecs_c.T

    samples = np.random.multivariate_normal(map_est, cov, size=n_mc)
    return map_est, cov, samples


# ============================================================
# Utility: Adaptive Metropolis-Hastings MCMC
# ============================================================

def adaptive_mcmc(log_post, x0, n_total=300000, n_warmup=100000):
    """Adaptive Metropolis-Hastings (Haario et al., 2001)."""
    d = len(x0)
    sd = 2.38 ** 2 / d  # optimal scaling factor
    eps = 1e-6

    x = x0.copy()
    lp = log_post(x)
    if not np.isfinite(lp):
        raise RuntimeError("Initial point has non-finite log-posterior")

    # Initialize running mean and covariance
    run_mean = x.copy()
    run_cov = 0.01 * np.eye(d)
    n_accept = 0

    samples = np.zeros((n_total - n_warmup, d))

    for i in range(n_total):
        # Proposal from adaptive Gaussian
        prop_cov = sd * run_cov + eps * np.eye(d)
        try:
            x_prop = np.random.multivariate_normal(x, prop_cov)
        except np.linalg.LinAlgError:
            x_prop = x + 0.01 * np.random.randn(d)

        lp_prop = log_post(x_prop)

        # Metropolis accept/reject
        if np.isfinite(lp_prop) and np.log(np.random.random()) < lp_prop - lp:
            x = x_prop
            lp = lp_prop
            n_accept += 1

        # Store post-warmup samples
        if i >= n_warmup:
            samples[i - n_warmup] = x

        # Update running statistics (Welford's algorithm)
        n = i + 1
        old_mean = run_mean.copy()
        run_mean = old_mean + (x - old_mean) / n
        if n > 1:
            run_cov = ((n - 2) / (n - 1)) * run_cov \
                      + (1.0 / n) * np.outer(x - old_mean, x - run_mean)

    rate = n_accept / n_total
    print(f"  Acceptance rate: {rate:.3f}")
    return samples


# ============================================================
# Model 1: Eight Schools — Adaptive MCMC
# ============================================================

def solve_eight_schools():
    print("Solving Eight Schools (MCMC)...")
    with open('/app/data/eight_schools.json') as f:
        data = json.load(f)

    J = data['J']
    y = np.array(data['y'], dtype=float)
    sigma = np.array(data['sigma'], dtype=float)

    def log_post(x):
        mu = x[0]
        log_tau = x[1]
        theta_tilde = x[2:2 + J]
        tau = np.exp(log_tau)

        lp = 0.0
        lp += -0.5 * mu * mu / 25.0
        lp += -np.log(1.0 + tau * tau / 25.0) + log_tau
        lp += -0.5 * np.sum(theta_tilde * theta_tilde)
        theta = mu + tau * theta_tilde
        lp += -0.5 * np.sum((y - theta) ** 2 / sigma ** 2)
        return lp

    # Start from a reasonable point
    x0 = np.zeros(2 + J)
    x0[0] = 4.0
    x0[1] = np.log(3.0)
    # Initialize theta_tilde from data
    for j in range(J):
        x0[2 + j] = (y[j] - 4.0) / 3.0

    samples = adaptive_mcmc(log_post, x0, n_total=400000, n_warmup=100000)

    mu_s = samples[:, 0]
    tau_s = np.exp(samples[:, 1])

    results = {}
    results['mu'] = float(np.mean(mu_s))
    results['tau'] = float(np.mean(tau_s))
    for j in range(J):
        tt_s = samples[:, 2 + j]
        results[f'theta_tilde[{j + 1}]'] = float(np.mean(tt_s))
        results[f'theta[{j + 1}]'] = float(np.mean(mu_s + tau_s * tt_s))

    print(f"  Estimated {len(results)} parameters")
    return results


# ============================================================
# Model 2: GP Regression — Laplace approximation
# ============================================================

def solve_gp_regr():
    print("Solving GP Regression (Laplace)...")
    with open('/app/data/gp_regr.json') as f:
        data = json.load(f)

    N = data['N']
    x_data = np.array(data['x'], dtype=float)
    y_data = np.array(data['y'], dtype=float)
    sq_dist = (x_data[:, None] - x_data[None, :]) ** 2

    def neg_log_post(z):
        log_rho, log_alpha, log_sigma = z
        rho = np.exp(log_rho)
        alpha = np.exp(log_alpha)
        sigma_val = np.exp(log_sigma)

        lp = 0.0
        lp += 25.0 * log_rho - 4.0 * rho
        lp += -0.5 * alpha * alpha / 4.0 + log_alpha
        lp += -0.5 * sigma_val * sigma_val + log_sigma

        K = alpha * alpha * np.exp(-0.5 * sq_dist / (rho * rho)) \
            + sigma_val * np.eye(N)
        try:
            L = cholesky(K, lower=True)
            v = solve_triangular(L, y_data, lower=True)
            lp += -0.5 * np.dot(v, v) \
                  - np.sum(np.log(np.diag(L))) \
                  - 0.5 * N * np.log(2 * np.pi)
        except np.linalg.LinAlgError:
            return 1e10
        return -lp

    x0 = np.array([np.log(6.0), np.log(2.0), np.log(1.5)])
    _, _, samples = laplace_sample(neg_log_post, x0, n_mc=100000)

    results = {
        'rho': float(np.mean(np.exp(samples[:, 0]))),
        'alpha': float(np.mean(np.exp(samples[:, 1]))),
        'sigma': float(np.mean(np.exp(samples[:, 2]))),
    }
    print(f"  Estimated {len(results)} parameters")
    return results


# ============================================================
# Model 3: SIR — Laplace approximation + ODE
# ============================================================

def solve_sir():
    print("Solving SIR Model (Laplace + ODE)...")
    with open('/app/data/sir.json') as f:
        data = json.load(f)

    N_t = data['N_t']
    t_obs = np.array(data['t'], dtype=float)
    y0 = np.array(data['y0'], dtype=float)
    stoi_hat = np.array(data['stoi_hat'], dtype=float)
    B_hat = np.array(data['B_hat'], dtype=float)
    kappa = 1e6

    def sir_rhs(t, state, beta, gamma_val, xi, delta_val):
        S, I, R, B = state
        force = beta * B / (B + kappa)
        return [-force * S, force * S - gamma_val * I,
                gamma_val * I, xi * I - delta_val * B]

    def solve_ode(beta, gamma_val, xi, delta_val):
        sol = solve_ivp(
            lambda t, y: sir_rhs(t, y, beta, gamma_val, xi, delta_val),
            [0, t_obs[-1] + 1], y0, t_eval=t_obs, method='RK45',
            rtol=1e-10, atol=1e-10)
        if sol.status != 0 or sol.y.shape[1] != N_t:
            return None
        return sol.y.T

    def neg_log_post(z):
        log_beta, log_gamma, log_xi, log_delta = z
        beta = np.exp(log_beta)
        gamma_val = np.exp(log_gamma)
        xi = np.exp(log_xi)
        delta_val = np.exp(log_delta)

        lp = 0.0
        lp += -np.log(1.0 + beta * beta / 6.25) + log_beta
        lp += -np.log(1.0 + gamma_val * gamma_val) + log_gamma
        lp += -np.log(1.0 + xi * xi / 625.0) + log_xi
        lp += -np.log(1.0 + delta_val * delta_val) + log_delta

        y_ode = solve_ode(beta, gamma_val, xi, delta_val)
        if y_ode is None:
            return 1e10

        lam = y0[0] - y_ode[0, 0]
        if lam <= 0:
            return 1e10
        lp += stoi_hat[0] * np.log(lam) - lam - gammaln(stoi_hat[0] + 1)
        for n in range(1, N_t):
            lam = y_ode[n - 1, 0] - y_ode[n, 0]
            if lam <= 0:
                return 1e10
            lp += stoi_hat[n] * np.log(lam) - lam - gammaln(stoi_hat[n] + 1)

        for n in range(N_t):
            if y_ode[n, 3] <= 0:
                return 1e10
            diff = np.log(B_hat[n]) - np.log(y_ode[n, 3])
            lp += -0.5 * diff * diff / 0.0225

        return -lp

    x0 = np.array([np.log(1.0), np.log(0.2), np.log(10.0), np.log(0.35)])
    _, _, samples = laplace_sample(neg_log_post, x0, n_mc=10000, n_restarts=10)

    beta_s = np.exp(samples[:, 0])
    gamma_s = np.exp(samples[:, 1])
    xi_s = np.exp(samples[:, 2])
    delta_s = np.exp(samples[:, 3])

    results = {}
    results['beta'] = float(np.mean(beta_s))
    results['gamma'] = float(np.mean(gamma_s))
    results['xi'] = float(np.mean(xi_s))
    results['delta'] = float(np.mean(delta_s))

    print(f"  Computing ODE solutions for {len(samples)} samples...")
    y_accum = np.zeros((N_t, 4))
    n_valid = 0
    for i in range(len(samples)):
        y_ode = solve_ode(beta_s[i], gamma_s[i], xi_s[i], delta_s[i])
        if y_ode is not None and np.all(np.isfinite(y_ode)) and np.all(y_ode[:, 0] >= 0):
            y_accum += y_ode
            n_valid += 1
    if n_valid == 0:
        raise RuntimeError("No valid ODE solutions")
    y_mean = y_accum / n_valid
    print(f"  {n_valid}/{len(samples)} valid ODE solutions")

    for n in range(N_t):
        for j in range(4):
            results[f'y[{n + 1},{j + 1}]'] = float(y_mean[n, j])

    print(f"  Estimated {len(results)} parameters")
    return results


# ============================================================
# Output
# ============================================================

def write_fit(results, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w') as f:
        for name, value in results.items():
            f.write(f"{name} {value:.6e}\n")


def main():
    es = solve_eight_schools()
    write_fit(es, '/app/results/eight_schools.fit')

    gp = solve_gp_regr()
    write_fit(gp, '/app/results/gp_regr.fit')

    sir = solve_sir()
    write_fit(sir, '/app/results/sir.fit')

    print("\nAll models solved. Results written to /app/results/")


if __name__ == '__main__':
    main()
