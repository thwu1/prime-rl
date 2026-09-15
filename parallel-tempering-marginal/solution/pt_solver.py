#!/usr/bin/env python3
"""
Solution: estimate log marginal likelihood for the unidentifiable binomial
model using power posteriors via CmdStan.
"""

import json
import math
import os
import subprocess
import sys
import numpy as np


CMDSTAN = os.environ.get('CMDSTAN', '/opt/cmdstan-2.35.0')


def create_tempered_model():
    """Create a Stan model with a temperature parameter on the likelihood."""
    stan_code = (
        "data {\n"
        "  int<lower=0> n_trials;\n"
        "  int<lower=0> n_successes;\n"
        "  real<lower=0> beta_temp;\n"
        "}\n"
        "parameters {\n"
        "  real<lower=0, upper=1> p1;\n"
        "  real<lower=0, upper=1> p2;\n"
        "}\n"
        "model {\n"
        "  target += beta_temp * binomial_lpmf(n_successes | n_trials, p1 * p2);\n"
        "}\n"
        "generated quantities {\n"
        "  real log_lik = binomial_lpmf(n_successes | n_trials, p1 * p2);\n"
        "  real p_product = p1 * p2;\n"
        "}\n"
    )
    model_path = '/app/tempered_model.stan'
    with open(model_path, 'w') as f:
        f.write(stan_code)
    return model_path


def compile_model(stan_path):
    """Compile a Stan model using CmdStan's make system."""
    exe_path = stan_path.replace('.stan', '')
    result = subprocess.run(
        ['make', exe_path],
        cwd=CMDSTAN,
        capture_output=True,
        text=True,
        timeout=300
    )
    if result.returncode != 0:
        print(f"Compilation stderr:\n{result.stderr}", file=sys.stderr)
        raise RuntimeError(f"CmdStan compilation failed with exit code {result.returncode}")
    print("Model compiled successfully.")
    return exe_path


def run_cmdstan(exe_path, data_file, output_file, seed, num_warmup=1000, num_samples=2000):
    """Run a CmdStan model and return parsed results."""
    cmd = [
        exe_path,
        'sample',
        f'num_warmup={num_warmup}',
        f'num_samples={num_samples}',
        'data', f'file={data_file}',
        'output', f'file={output_file}',
        'random', f'seed={seed}',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"CmdStan run warning (seed={seed}):\n{result.stderr[-300:]}", file=sys.stderr)
    return parse_cmdstan_csv(output_file)


def parse_cmdstan_csv(csv_path):
    """Parse CmdStan's CSV output format, skipping comment lines."""
    headers = None
    rows = []
    with open(csv_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            if headers is None:
                headers = parts
                continue
            rows.append([float(x) for x in parts])
    if headers is None or len(rows) == 0:
        raise RuntimeError(f"No data parsed from {csv_path}")
    data = {}
    for i, h in enumerate(headers):
        data[h] = np.array([row[i] for row in rows])
    return data


def compute_log_lik_uniform(n_trials, n_successes, n_samples, rng):
    """Compute log-likelihood values for uniform prior samples (beta=0)."""
    log_binom = (
        math.lgamma(n_trials + 1)
        - math.lgamma(n_successes + 1)
        - math.lgamma(n_trials - n_successes + 1)
    )
    p1_vals = rng.uniform(1e-10, 1.0 - 1e-10, n_samples)
    p2_vals = rng.uniform(1e-10, 1.0 - 1e-10, n_samples)
    log_liks = np.empty(n_samples)
    for i in range(n_samples):
        p = p1_vals[i] * p2_vals[i]
        if 0 < p < 1:
            log_liks[i] = log_binom + n_successes * math.log(p) + (n_trials - n_successes) * math.log(1.0 - p)
        else:
            log_liks[i] = -1e100
    return log_liks


def stepping_stone_log_z(all_log_liks, betas):
    """Stepping stone estimator for log(Z_1/Z_0)."""
    log_z = 0.0
    for i in range(len(betas) - 1):
        db = betas[i + 1] - betas[i]
        ll = all_log_liks[i]
        shifted = db * ll
        max_val = np.max(shifted)
        if not np.isfinite(max_val):
            continue
        log_z += max_val + np.log(np.mean(np.exp(shifted - max_val)))
    return float(log_z)


def main():
    with open('/app/data.json') as f:
        data = json.load(f)
    n_trials = data['n_trials']
    n_successes = data['n_successes']

    print("Creating tempered Stan model...")
    model_path = create_tempered_model()

    print("Compiling with CmdStan...")
    exe_path = compile_model(model_path)

    # Temperature schedule
    n_temps = 25
    betas = [i / (n_temps - 1) for i in range(n_temps)]

    rng = np.random.default_rng(42)
    n_uniform_samples = 4000
    n_stan_samples = 2000

    # beta=0: generate uniform samples directly
    print(f"Temperature 0/{n_temps-1} (beta=0.000): uniform samples...")
    log_liks_uniform = compute_log_lik_uniform(n_trials, n_successes, n_uniform_samples, rng)
    all_log_liks = [log_liks_uniform]
    all_p_products = [None]  # Not needed for stepping stone at beta=0

    # beta > 0: run CmdStan at each temperature
    for idx in range(1, n_temps):
        beta = betas[idx]
        print(f"Temperature {idx}/{n_temps-1} (beta={beta:.4f})...")

        data_file = f'/app/data_beta_{idx}.json'
        temp_data = {
            'n_trials': n_trials,
            'n_successes': n_successes,
            'beta_temp': float(beta)
        }
        with open(data_file, 'w') as f:
            json.dump(temp_data, f)

        output_file = f'/app/output_beta_{idx}.csv'
        seed = 1000 + idx

        parsed = run_cmdstan(exe_path, data_file, output_file, seed,
                             num_warmup=1000, num_samples=n_stan_samples)

        all_log_liks.append(parsed['log_lik'])
        all_p_products.append(parsed['p_product'])

    # Compute log marginal likelihood via stepping stone
    log_ml = stepping_stone_log_z(all_log_liks, betas)
    print(f"\nStepping stone log ML: {log_ml:.4f}")

    # Posterior summaries from the beta=1 chain
    target_p = all_p_products[-1]
    posterior_mean_p = float(np.mean(target_p))
    posterior_std_p = float(np.std(target_p, ddof=0))

    results = {
        'log_marginal_likelihood': log_ml,
        'posterior_mean_p': posterior_mean_p,
        'posterior_std_p': posterior_std_p,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to /app/results.json:")
    print(f"  log_marginal_likelihood: {log_ml:.4f}")
    print(f"  posterior_mean_p: {posterior_mean_p:.4f}")
    print(f"  posterior_std_p: {posterior_std_p:.4f}")


if __name__ == '__main__':
    main()
