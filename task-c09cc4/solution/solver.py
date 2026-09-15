#!/usr/bin/env python3
"""
Distributed Training Checkpoint Optimizer

Computes optimal checkpoint intervals and expected training times
under exponential and Weibull failure models using renewal theory,
numerical optimization, and Monte Carlo simulation.
"""

import hashlib
import json
import os
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.integrate import quad
from scipy.special import gamma
from scipy.stats import weibull_min


# Use /opt/task_data/ as the authoritative config path (survives volume mounts).
# Fall back to /app/config.json if the opt path is missing.
CONFIG_PATH = '/opt/task_data/config.json' if os.path.exists('/opt/task_data/config.json') else '/app/config.json'


def compute_system_params(scenario):
    """Compute system-level Weibull parameters and MTBF."""
    N = scenario['num_workers']
    mtbf_worker_sec = scenario['failure_model']['mtbf_hours_per_worker'] * 3600.0
    k = scenario['failure_model'].get('shape', 1.0)

    lam_worker = mtbf_worker_sec / gamma(1.0 + 1.0 / k)
    lam_sys = lam_worker * N ** (-1.0 / k)
    mtbf_sys = lam_sys * gamma(1.0 + 1.0 / k)

    return k, lam_sys, mtbf_sys


def expected_complete_time(tau, k, lam_sys, R):
    """
    Expected wall-clock time to successfully complete one interval of
    duration tau seconds, with Weibull(k, lam_sys) failure distribution,
    age-reset after each failure, and recovery cost R.

    Uses renewal theory:
      E[T] = (1/S(tau) - 1) * (E[X|X<tau] + R) + tau
    """
    if tau <= 0:
        return 0.0

    S_tau = np.exp(-(tau / lam_sys) ** k)

    if S_tau > 1.0 - 1e-15:
        return tau

    F_tau = 1.0 - S_tau

    integral, _ = quad(
        lambda x: x * weibull_min.pdf(x, k, scale=lam_sys),
        0, tau, limit=200
    )
    E_trunc = integral / F_tau

    n_failures_expected = 1.0 / S_tau - 1.0
    return n_failures_expected * (E_trunc + R) + tau


def expected_total_time(delta, W, C, k, lam_sys, R):
    """
    Expected total wall-clock time to complete W seconds of useful work
    with periodic checkpointing every delta seconds.

    Structure: floor(W/delta) full intervals (delta work + C checkpoint)
    followed by an optional partial interval (remaining work, no checkpoint).
    """
    if delta <= 0:
        return float('inf')

    n_full = int(W // delta)
    W_remain = W - n_full * delta

    total = 0.0
    if n_full > 0:
        tau_full = delta + C
        E_interval = expected_complete_time(tau_full, k, lam_sys, R)
        total += n_full * E_interval

    if W_remain > 1e-10:
        E_last = expected_complete_time(W_remain, k, lam_sys, R)
        total += E_last

    return total


def find_optimal_interval(W, C, R, k, lam_sys, iter_time):
    """Find optimal checkpoint interval minimizing expected total time."""
    if C <= 0:
        return iter_time

    result = minimize_scalar(
        lambda delta: expected_total_time(delta, W, C, k, lam_sys, R),
        bounds=(iter_time, W),
        method='bounded',
        options={'xatol': 0.01}
    )
    return result.x


def simulate_strategy(W, delta, C, R, k, lam_sys, rng, num_sims):
    """
    Monte Carlo simulation of a checkpoint strategy.

    Uses geometric distribution shortcut: for each checkpoint interval,
    draw the number of failed attempts before success, then draw the
    exact failure times using inverse CDF of truncated Weibull.
    """
    results = np.zeros(num_sims)

    n_full = int(W // delta)
    W_remain = W - n_full * delta

    tau_full = delta + C
    p_survive_full = np.exp(-(tau_full / lam_sys) ** k)
    F_full = 1.0 - p_survive_full

    has_partial = W_remain > 1e-10
    if has_partial:
        p_survive_last = np.exp(-(W_remain / lam_sys) ** k)
        F_last = 1.0 - p_survive_last

    for sim in range(num_sims):
        total_time = 0.0

        # Full intervals
        if n_full > 0:
            attempts = rng.geometric(p_survive_full, size=n_full)
            n_failures = int(np.sum(attempts)) - n_full
            total_time += n_full * tau_full

            if n_failures > 0 and F_full > 1e-15:
                u_vals = rng.random(n_failures)
                fail_times = lam_sys * (
                    -np.log(1.0 - u_vals * F_full)
                ) ** (1.0 / k)
                total_time += np.sum(fail_times) + n_failures * R

        # Partial last interval (no checkpoint cost)
        if has_partial:
            attempts_last = rng.geometric(p_survive_last)
            n_fail_last = int(attempts_last) - 1
            total_time += W_remain

            if n_fail_last > 0 and F_last > 1e-15:
                u_vals = rng.random(n_fail_last)
                fail_times = lam_sys * (
                    -np.log(1.0 - u_vals * F_last)
                ) ** (1.0 / k)
                total_time += np.sum(fail_times) + n_fail_last * R

        results[sim] = total_time

    return results


def mc_stats(samples):
    """Compute mean, std, and 95% confidence interval."""
    mean = float(np.mean(samples))
    std = float(np.std(samples, ddof=1))
    n = len(samples)
    ci_half = 1.96 * std / np.sqrt(n)
    return {
        'mean': mean,
        'std': std,
        'ci_lower': mean - ci_half,
        'ci_upper': mean + ci_half,
    }


def analyze_scenario(scenario):
    """Perform full checkpoint analysis for one scenario."""
    iter_time = scenario['iteration_time_sec']
    total_iter = scenario['total_iterations']
    C = scenario['checkpoint_cost_sec']
    R = scenario['recovery_cost_sec']
    fixed_interval_iter = scenario['fixed_checkpoint_interval_iter']
    num_sims = scenario['num_simulations']
    seed = scenario['random_seed']

    W = total_iter * iter_time
    base_time = W

    k, lam_sys, mtbf_sys = compute_system_params(scenario)

    # Optimal checkpoint interval
    delta_opt = find_optimal_interval(W, C, R, k, lam_sys, iter_time)
    delta_opt_iter = max(1, round(delta_opt / iter_time))
    delta_opt_aligned = delta_opt_iter * iter_time

    # Expected times
    E_no = expected_complete_time(W, k, lam_sys, R)
    E_opt = expected_total_time(delta_opt_aligned, W, C, k, lam_sys, R)
    delta_fixed = fixed_interval_iter * iter_time
    E_fixed = expected_total_time(delta_fixed, W, C, k, lam_sys, R)
    E_zero = expected_total_time(iter_time, W, 0, k, lam_sys, R)

    # Overhead ratios
    overhead = {
        'no_checkpoint': (E_no - base_time) / base_time,
        'optimal_periodic': (E_opt - base_time) / base_time,
        'fixed_periodic': (E_fixed - base_time) / base_time,
        'zero_cost_per_iter': (E_zero - base_time) / base_time,
    }

    # Monte Carlo simulation
    rng = np.random.default_rng(seed)

    mc_no = simulate_strategy(W, W, 0, R, k, lam_sys, rng, num_sims)
    mc_opt = simulate_strategy(W, delta_opt_aligned, C, R, k, lam_sys, rng, num_sims)
    mc_fix = simulate_strategy(W, delta_fixed, C, R, k, lam_sys, rng, num_sims)
    mc_zero = simulate_strategy(W, iter_time, 0, R, k, lam_sys, rng, num_sims)

    return {
        'system_mtbf_sec': float(mtbf_sys),
        'optimal_checkpoint_interval_sec': float(delta_opt_aligned),
        'optimal_checkpoint_interval_iter': int(delta_opt_iter),
        'expected_time': {
            'no_checkpoint_sec': float(E_no),
            'optimal_periodic_sec': float(E_opt),
            'fixed_periodic_sec': float(E_fixed),
            'zero_cost_per_iter_sec': float(E_zero),
        },
        'overhead_ratio': {k_: float(v) for k_, v in overhead.items()},
        'monte_carlo': {
            'no_checkpoint': mc_stats(mc_no),
            'optimal_periodic': mc_stats(mc_opt),
            'fixed_periodic': mc_stats(mc_fix),
            'zero_cost_per_iter': mc_stats(mc_zero),
        },
    }


def compute_verification_digest(task_dna, scenario_results, scenario_order):
    """Compute SHA-256 verification digest from DNA + computed values."""
    parts = [task_dna]
    for name in scenario_order:
        sr = scenario_results[name]
        parts.append(f"{sr['system_mtbf_sec']:.2f}")
        parts.append(str(sr['optimal_checkpoint_interval_iter']))
    digest_input = "|".join(parts)
    return hashlib.sha256(digest_input.encode()).hexdigest()


def main():
    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)

    task_dna = config['task_dna']
    scenario_order = [s['name'] for s in config['scenarios']]

    output = {
        'task_dna': task_dna,
        'scenarios': {},
    }

    for scenario in config['scenarios']:
        name = scenario['name']
        print(f"Analyzing scenario: {name}")
        output['scenarios'][name] = analyze_scenario(scenario)
        print(f"  System MTBF: {output['scenarios'][name]['system_mtbf_sec']:.1f}s")
        print(f"  Optimal interval: {output['scenarios'][name]['optimal_checkpoint_interval_iter']} iterations")
        et = output['scenarios'][name]['expected_time']
        print(f"  E[T] no_ckpt={et['no_checkpoint_sec']:.1f}  opt={et['optimal_periodic_sec']:.1f}"
              f"  fixed={et['fixed_periodic_sec']:.1f}  zero={et['zero_cost_per_iter_sec']:.1f}")

    # Compute verification digest
    output['verification_digest'] = compute_verification_digest(
        task_dna, output['scenarios'], scenario_order
    )
    print(f"\nVerification digest: {output['verification_digest']}")

    with open('/app/results.json', 'w') as f:
        json.dump(output, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
