#!/usr/bin/env python3
"""
Bayesian posterior inference via adaptive Metropolis-Hastings MCMC for the
Eight Schools hierarchical model, GP Regression model, and SIR epidemic model.

Produces posterior mean estimates in .fit format for evaluation against
ground truth via z-score criterion.
"""


import numpy as np
import json
import os
import math


# ---------------------------------------------------------------------------
# Adaptive Metropolis-Hastings MCMC
# ---------------------------------------------------------------------------

def adaptive_mcmc(log_post_fn, dim, n_warmup, n_samples, init, seed=42):
    """
    Metropolis-Hastings with empirical covariance adaptation during warmup.
    Uses the Roberts-Rosenthal optimal scaling (2.38^2 / d) with an
    empirical covariance estimated from warmup samples.

    log_post_fn: callable(params_array) -> float
    """
    rng = np.random.RandomState(seed)
    current = init.copy()
    current_lp = log_post_fn(current)

    if not np.isfinite(current_lp):
        raise ValueError(
            f"Initial log-posterior is {current_lp}. Check init values."
        )

    optimal_scale = 2.38 ** 2 / dim
    prop_cov = np.eye(dim) * 0.25

    # Warmup with covariance adaptation
    warmup_buf = []
    for i in range(n_warmup):
        z = rng.multivariate_normal(np.zeros(dim), prop_cov)
        candidate = current + z
        candidate_lp = log_post_fn(candidate)
        if (np.isfinite(candidate_lp)
                and np.log(rng.random()) < candidate_lp - current_lp):
            current = candidate
            current_lp = candidate_lp
        warmup_buf.append(current.copy())

        if (i + 1) % 500 == 0 and len(warmup_buf) >= 1000:
            recent = np.array(warmup_buf[-min(len(warmup_buf), 5000):])
            emp_cov = np.cov(recent.T)
            if np.all(np.isfinite(emp_cov)):
                prop_cov = optimal_scale * emp_cov + 1e-8 * np.eye(dim)

    # Sampling phase
    samples = np.zeros((n_samples, dim))
    n_accept = 0
    for i in range(n_samples):
        z = rng.multivariate_normal(np.zeros(dim), prop_cov)
        candidate = current + z
        candidate_lp = log_post_fn(candidate)
        if (np.isfinite(candidate_lp)
                and np.log(rng.random()) < candidate_lp - current_lp):
            current = candidate
            current_lp = candidate_lp
            n_accept += 1
        samples[i] = current

    rate = n_accept / n_samples
    print(f"  Acceptance rate: {rate:.3f} ({n_samples} samples, dim={dim})")
    return samples


# ---------------------------------------------------------------------------
# Inlined RK4 ODE solver for SIR model (avoids function call overhead)
# ---------------------------------------------------------------------------

def sir_ode_trajectory(y0_S, y0_I, y0_R, y0_B, t_obs_list,
                       beta, kappa, gamma_p, xi, delta_p, n_steps=50):
    """
    Fast inlined RK4 for the SIR ODE system. Returns list of (S,I,R,B)
    tuples at each observation time, or None if solution is invalid.
    Uses pure-Python scalar arithmetic to avoid NumPy overhead on tiny arrays.
    """
    S = float(y0_S)
    I = float(y0_I)
    R = float(y0_R)
    B = float(y0_B)
    t_current = 0.0
    solutions = []

    for t_target in t_obs_list:
        dt = (t_target - t_current) / n_steps
        hdt = dt * 0.5
        sdt = dt / 6.0

        for _ in range(n_steps):
            # k1
            force = beta * B / (B + kappa) * S
            dS1 = -force
            dI1 = force - gamma_p * I
            dR1 = gamma_p * I
            dB1 = xi * I - delta_p * B

            # k2
            S2 = S + hdt * dS1
            I2 = I + hdt * dI1
            B2 = B + hdt * dB1
            force = beta * B2 / (B2 + kappa) * S2
            dS2 = -force
            dI2 = force - gamma_p * I2
            dR2 = gamma_p * I2
            dB2 = xi * I2 - delta_p * B2

            # k3
            S3 = S + hdt * dS2
            I3 = I + hdt * dI2
            B3 = B + hdt * dB2
            force = beta * B3 / (B3 + kappa) * S3
            dS3 = -force
            dI3 = force - gamma_p * I3
            dR3 = gamma_p * I3
            dB3 = xi * I3 - delta_p * B3

            # k4
            S4 = S + dt * dS3
            I4 = I + dt * dI3
            B4 = B + dt * dB3
            force = beta * B4 / (B4 + kappa) * S4
            dS4 = -force
            dI4 = force - gamma_p * I4
            dR4 = gamma_p * I4
            dB4 = xi * I4 - delta_p * B4

            # Update state
            S += sdt * (dS1 + 2 * dS2 + 2 * dS3 + dS4)
            I += sdt * (dI1 + 2 * dI2 + 2 * dI3 + dI4)
            R += sdt * (dR1 + 2 * dR2 + 2 * dR3 + dR4)
            B += sdt * (dB1 + 2 * dB2 + 2 * dB3 + dB4)
            t_current += dt

        # NaN / non-physical check
        if S != S or I != I or B != B:
            return None
        if S < -1.0 or I < -1.0 or B < -1.0:
            return None

        solutions.append((S, I, R, B))

    return solutions


# ---------------------------------------------------------------------------
# Model-specific inference runners
# ---------------------------------------------------------------------------

def solve_eight_schools():
    """Run MCMC inference for the Eight Schools model."""
    print("=== Eight Schools ===")
    with open('/app/models/eight_schools/data.json') as f:
        data = json.load(f)

    J = data['J']
    y_obs = np.array(data['y'], dtype=float)
    sigma_obs = np.array(data['sigma'], dtype=float)
    dim = 2 + J

    def log_post(params):
        mu = params[0]
        log_tau = params[1]
        tau = math.exp(log_tau)
        theta_tilde = params[2:2 + J]
        theta = mu + tau * theta_tilde

        lp = 0.0
        # Prior: mu ~ Normal(0, 5)
        lp -= 0.5 * (mu / 5.0) ** 2
        # Prior: tau ~ Half-Cauchy(0, 5), with Jacobian for log-transform
        lp -= math.log(1.0 + (tau / 5.0) ** 2)
        lp += log_tau
        # Prior: theta_tilde ~ Normal(0, 1)
        lp -= 0.5 * np.sum(theta_tilde ** 2)
        # Likelihood: y ~ Normal(theta, sigma)
        lp -= 0.5 * np.sum(((y_obs - theta) / sigma_obs) ** 2)
        return lp

    init = np.zeros(dim)
    init[1] = 1.0  # log(tau) => tau ~ 2.7

    samples = adaptive_mcmc(
        log_post, dim,
        n_warmup=50000, n_samples=300000,
        init=init, seed=20240101
    )

    mu_samples = samples[:, 0]
    tau_samples = np.exp(samples[:, 1])
    theta_tilde_samples = samples[:, 2:2 + J]
    # Compute theta per-sample (nonlinear transform), then average
    theta_samples = (mu_samples[:, None]
                     + tau_samples[:, None] * theta_tilde_samples)

    results = {}
    results['mu'] = float(np.mean(mu_samples))
    results['tau'] = float(np.mean(tau_samples))
    for j in range(J):
        results[f'theta_tilde[{j + 1}]'] = float(
            np.mean(theta_tilde_samples[:, j])
        )
    for j in range(J):
        results[f'theta[{j + 1}]'] = float(np.mean(theta_samples[:, j]))

    return results


def solve_gp_regr():
    """Run MCMC inference for the GP Regression model."""
    print("=== GP Regression ===")
    with open('/app/models/gp_regr/data.json') as f:
        data = json.load(f)

    x = np.array(data['x'], dtype=float)
    y_obs = np.array(data['y'], dtype=float)
    N = len(x)
    diffs = x[:, None] - x[None, :]
    dim = 3
    log_2pi_N = N * math.log(2.0 * math.pi)

    def log_post(params):
        log_rho, log_alpha, log_sigma = params
        rho = math.exp(log_rho)
        alpha = math.exp(log_alpha)
        sigma = math.exp(log_sigma)

        # Squared exponential kernel + noise
        K = alpha ** 2 * np.exp(-0.5 * diffs ** 2 / rho ** 2)
        cov = K + sigma * np.eye(N)

        try:
            L = np.linalg.cholesky(cov)
        except np.linalg.LinAlgError:
            return -np.inf

        v = np.linalg.solve(L, y_obs)
        log_det = 2.0 * np.sum(np.log(np.diag(L)))
        lp = -0.5 * (np.dot(v, v) + log_det + log_2pi_N)

        # Priors
        lp += 24.0 * math.log(rho) - 4.0 * rho   # Gamma(25, 4)
        lp -= 0.5 * (alpha / 2.0) ** 2              # Half-Normal(0, 2)
        lp -= 0.5 * sigma ** 2                       # Half-Normal(0, 1)

        # Jacobian for log-transforms
        lp += log_rho + log_alpha + log_sigma
        return lp

    init = np.array([math.log(6.5), math.log(2.2), math.log(1.7)])

    samples = adaptive_mcmc(
        log_post, dim,
        n_warmup=30000, n_samples=150000,
        init=init, seed=20250101
    )

    results = {
        'rho': float(np.mean(np.exp(samples[:, 0]))),
        'alpha': float(np.mean(np.exp(samples[:, 1]))),
        'sigma': float(np.mean(np.exp(samples[:, 2]))),
    }

    return results


def solve_sir():
    """Run MCMC inference for the SIR epidemic model with inlined ODE."""
    print("=== SIR Epidemic ===")
    with open('/app/models/sir/data.json') as f:
        data = json.load(f)

    N_t = data['N_t']
    t_obs = [float(t) for t in data['t']]
    stoi_hat = [float(s) for s in data['stoi_hat']]
    B_hat = [float(b) for b in data['B_hat']]
    y0 = [float(v) for v in data['y0']]
    kappa = 1e6

    # Precompute constants for lognormal likelihood
    log_B_hat = [math.log(b) for b in B_hat]
    log_015 = math.log(0.15)

    def log_post(params):
        log_beta = params[0]
        log_gamma = params[1]
        log_xi = params[2]
        log_delta = params[3]
        beta = math.exp(log_beta)
        gamma_p = math.exp(log_gamma)
        xi = math.exp(log_xi)
        delta_p = math.exp(log_delta)

        # Solve ODE with inlined RK4
        sol = sir_ode_trajectory(
            y0[0], y0[1], y0[2], y0[3],
            t_obs, beta, kappa, gamma_p, xi, delta_p, 50
        )
        if sol is None:
            return -np.inf

        lp = 0.0

        # Poisson likelihood for new infections
        prev_S = y0[0]
        for n in range(N_t):
            S_n = sol[n][0]
            rate = prev_S - S_n
            if rate <= 0:
                return -np.inf
            lp += stoi_hat[n] * math.log(rate) - rate
            prev_S = S_n

        # Lognormal likelihood for pathogen concentration
        for n in range(N_t):
            B_n = sol[n][3]
            if B_n <= 0:
                return -np.inf
            lp += (-0.5 * ((log_B_hat[n] - math.log(B_n)) / 0.15) ** 2
                   - log_B_hat[n] - log_015)

        # Half-Cauchy priors
        lp -= math.log(1.0 + (beta / 2.5) ** 2)
        lp -= math.log(1.0 + gamma_p ** 2)
        lp -= math.log(1.0 + (xi / 25.0) ** 2)
        lp -= math.log(1.0 + delta_p ** 2)

        # Jacobian for log-transforms
        lp += log_beta + log_gamma + log_xi + log_delta
        return lp

    dim = 4
    init = np.array([
        math.log(1.0), math.log(0.2), math.log(10.0), math.log(0.35)
    ])

    samples = adaptive_mcmc(
        log_post, dim,
        n_warmup=30000, n_samples=100000,
        init=init, seed=20240303
    )

    beta_samples = np.exp(samples[:, 0])
    gamma_samples = np.exp(samples[:, 1])
    xi_samples = np.exp(samples[:, 2])
    delta_samples = np.exp(samples[:, 3])

    results = {
        'beta': float(np.mean(beta_samples)),
        'gamma': float(np.mean(gamma_samples)),
        'xi': float(np.mean(xi_samples)),
        'delta': float(np.mean(delta_samples)),
    }

    # Compute transformed parameters: solve ODE for thinned samples, average
    print("  Computing ODE-derived transformed parameters...")
    thin = max(1, len(samples) // 5000)
    thinned = samples[::thin]
    print(f"  Using {len(thinned)} thinned samples for ODE averaging")

    y_accum = [[0.0] * 4 for _ in range(N_t)]
    n_valid = 0

    for s in thinned:
        beta_s = math.exp(s[0])
        gamma_s = math.exp(s[1])
        xi_s = math.exp(s[2])
        delta_s = math.exp(s[3])

        sol = sir_ode_trajectory(
            y0[0], y0[1], y0[2], y0[3],
            t_obs, beta_s, kappa, gamma_s, xi_s, delta_s, 50
        )
        if sol is not None:
            for t_idx in range(N_t):
                for k_idx in range(4):
                    y_accum[t_idx][k_idx] += sol[t_idx][k_idx]
            n_valid += 1

    if n_valid == 0:
        raise RuntimeError("No valid ODE solutions obtained")

    print(f"  {n_valid}/{len(thinned)} valid ODE evaluations")

    for t_idx in range(N_t):
        for k_idx in range(4):
            name = f"y[{t_idx + 1},{k_idx + 1}]"
            results[name] = y_accum[t_idx][k_idx] / n_valid

    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_fit_file(results, filepath):
    """Write posterior means in .fit format (param_name mean)."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w') as f:
        for name, val in results.items():
            f.write(f"{name} {val:.6e}\n")
    print(f"  Written: {filepath}")


def main():
    es_results = solve_eight_schools()
    write_fit_file(es_results, '/app/results/eight_schools.fit')
    print()

    gp_results = solve_gp_regr()
    write_fit_file(gp_results, '/app/results/gp_regr.fit')
    print()

    sir_results = solve_sir()
    write_fit_file(sir_results, '/app/results/sir.fit')
    print()

    print("Done.")


if __name__ == '__main__':
    main()
