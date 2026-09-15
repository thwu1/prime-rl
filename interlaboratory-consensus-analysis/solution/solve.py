#!/usr/bin/env python3
"""

Solution: Port NICOB R source to Python. Reads .ncb files, performs
full consensus analysis, writes JSON results.
"""

import json
import os
import glob as globmod
import numpy as np
from scipy import stats


def read_ncb(filepath):
    """Parse NICOB's .ncb configuration format."""
    config = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if '=' in line:
                key, value = line.split('=', 1)
                config[key.strip()] = value.strip()

    labs = [s.strip() for s in config['lablabels'].split(',')]
    x = np.array([float(v.strip()) for v in config['mean'].split(',') if v.strip()])
    u = np.array([float(v.strip()) for v in config['se'].split(',') if v.strip()])

    df_str = config.get('df', '').strip()
    if df_str:
        df = np.array([float(v.strip()) for v in df_str.split(',') if v.strip()])
    else:
        df = None

    return labs, x, u, df


def dl_estimate(x, u):
    """
    Port of modifiedKHmethod.R: DerSimonian-Laird random effects
    meta-analysis with moment estimator for between-lab variance.
    """
    n = len(x)
    w0 = 1.0 / u**2
    x0 = np.sum(w0 * x) / np.sum(w0)
    Q = np.sum(w0 * (x - x0)**2)
    c = np.sum(w0) - np.sum(w0**2) / np.sum(w0)
    tau2 = max(0.0, (Q - (n - 1)) / c)
    w = 1.0 / (u**2 + tau2)
    mu = np.sum(w * x) / np.sum(w)
    I2 = max(0.0, (Q - (n - 1)) / Q * 100.0) if Q > 0 else 0.0
    return mu, tau2, Q, I2


def hksj_interval(x, u, mu, tau2, coverage=0.95):
    """
    Port of modifiedKHmethod.R: Modified Hartung-Knapp-Sidik-Jonkman
    confidence interval with q* = max(1, q) correction.
    """
    n = len(x)
    w = 1.0 / (u**2 + tau2)
    q = np.sum(w * (x - mu)**2) / (n - 1)
    qstar = max(1.0, q)
    se = np.sqrt(qstar / np.sum(w))
    df = n - 1
    t_upper = stats.t.ppf((1 + coverage) / 2, df)
    t_lower = stats.t.ppf((1 - coverage) / 2, df)
    ci_upper = mu + np.sqrt(qstar) * se * t_upper
    ci_lower = mu + np.sqrt(qstar) * se * t_lower
    return ci_lower, ci_upper


def phi_factor(nu):
    """
    Port of linearOP.R: Scale factor for t-distribution.
    For nu > 2: phi = sqrt(nu/(nu-2))
    For nu <= 2: Koepke-Possolo approximation from the R code.
    """
    if nu > 2:
        return np.sqrt(nu / (nu - 2))
    else:
        a = 0.4668994
        b = -0.3998882
        return 1.5 * ((1 - (3.0 / 4.0) * (a - 4.0 * b * (nu**(-3.0 / 4.0) - 1) / 3.0))**(-4.0 / 3.0))


def linear_pool(x, u, df, n_samples=500000, seed=42):
    """
    Port of linearOP.R: Linear Opinion Pool consensus via MC.
    Equal weights, samples lab indices uniformly, draws from
    scaled t(df) or Normal depending on df availability.
    """
    rng = np.random.RandomState(seed)
    n = len(x)
    indices = rng.randint(0, n, size=n_samples)
    samples = np.empty(n_samples)

    for j in range(n):
        mask = indices == j
        cnt = int(np.sum(mask))
        if cnt == 0:
            continue
        if df is None or np.isinf(df[j]):
            samples[mask] = rng.normal(loc=x[j], scale=u[j], size=cnt)
        else:
            nu = df[j]
            phi = phi_factor(nu)
            factor = u[j] / phi
            samples[mask] = x[j] + rng.standard_t(nu, size=cnt) * factor

    return float(np.mean(samples))


def sample_tau2_bt(x, u, rng):
    """
    Port of sampleFromTau2Dist.R: Biggerstaff-Tweedie location-shifted
    scaled gamma approximation for the distribution of tau^2.
    """
    n = len(x)
    w = 1.0 / u**2
    S1 = np.sum(w)
    S2 = np.sum(w**2)
    S3 = np.sum(w**3)
    c = S1 - S2 / S1
    muhat = np.sum(w * x) / S1
    Q = np.sum(w * (x - muhat)**2)

    if c == 0:
        return 0.0

    tau2_hat_M = (Q - (n - 1)) / c

    E_Q = (n - 1) + (S1 - S2 / S1) * tau2_hat_M
    Var_Q = (2.0 * (n - 1)
             + 4.0 * (S1 - S2 / S1) * tau2_hat_M
             + 2.0 * (S2 - 2.0 * S3 / S1 + S2**2 / S1**2) * tau2_hat_M**2)

    if Var_Q <= 0:
        Var_Q = 1e-10

    lam = E_Q / Var_Q
    r = E_Q**2 / Var_Q

    transformed_Q = rng.gamma(shape=r, scale=1.0 / lam)
    return max(0.0, (transformed_Q - (n - 1)) / c)


def symmetrical_bootstrap_ci(x, estimate, coverage):
    """
    Port of symmetricalBootstrapCI.R: Binary search for the smallest
    U such that fraction of |x - estimate| <= U meets the coverage.
    """
    m = len(x)
    Umax = np.max(np.abs(x - estimate))
    Udelta = (np.max(x) - np.min(x)) / m
    x1 = Umax
    x0 = 0.0
    iteration = 1
    while iteration < 1e7 and (x1 - x0) > Udelta:
        iteration += 1
        x3 = (x1 + x0) / 2.0
        if np.sum((estimate - x3 <= x) & (x <= estimate + x3)) / m < coverage:
            x0 = x3
        else:
            x1 = x3
    return (x1 + x0) / 2.0


def compute_doe_mra(x, u, df, mu, tau2, n_boot=10000, seed=123, coverage=0.95):
    """
    Port of DoEUnilateralDerSimonianLaird.R (MRA branch, LOO=FALSE):
    Parametric bootstrap for unilateral Degrees of Equivalence.
    """
    rng = np.random.RandomState(seed)
    n = len(x)
    doe_x = x - mu

    D = np.empty((n_boot, n))

    for k in range(n_boot):
        tau2_B = sample_tau2_bt(x, u, rng)
        x_B = rng.normal(loc=mu, scale=np.sqrt(tau2_B + u**2))

        u_B = u.copy()
        if df is not None:
            finite = np.isfinite(df)
            if np.any(finite):
                chi2_vals = rng.chisquare(df=df[finite])
                u_B[finite] = u[finite] * np.sqrt(df[finite] / chi2_vals)

        # DL consensus on bootstrap data (equivalent to rma(method="DL")$b)
        w_B0 = 1.0 / u_B**2
        x0_B = np.sum(w_B0 * x_B) / np.sum(w_B0)
        Q_B = np.sum(w_B0 * (x_B - x0_B)**2)
        c_B = np.sum(w_B0) - np.sum(w_B0**2) / np.sum(w_B0)
        tau2_B_dl = max(0.0, (Q_B - (n - 1)) / c_B) if c_B != 0 else 0.0
        w_B = 1.0 / (u_B**2 + tau2_B_dl)
        mu_B = np.sum(w_B * x_B) / np.sum(w_B)

        D[k, :] = x_B - mu_B

    # Center then shift (sweep operations from R code)
    D_centered = D - D.mean(axis=0)
    D_final = D_centered + doe_x

    results = {}
    for j in range(n):
        U95 = float(symmetrical_bootstrap_ci(D_final[:, j], doe_x[j], coverage))
        sig = bool(abs(doe_x[j]) > U95)
        results[j] = {'value': float(doe_x[j]), 'U95': U95, 'significant': sig}

    return results


def process_dataset(filepath):
    """Process a single .ncb dataset through all analysis procedures."""
    labs, x, u, df = read_ncb(filepath)

    mu, tau2, Q, I2 = dl_estimate(x, u)
    ci_lower, ci_upper = hksj_interval(x, u, mu, tau2)
    lp = linear_pool(x, u, df)

    doe_raw = compute_doe_mra(x, u, df, mu, tau2)
    doe = {}
    for j, lab in enumerate(labs):
        doe[lab] = doe_raw[j]

    return {
        'consensus_dl': float(mu),
        'tau_squared': float(tau2),
        'tau': float(np.sqrt(tau2)),
        'cochran_q': float(Q),
        'i_squared': float(I2),
        'hksj_ci': [float(ci_lower), float(ci_upper)],
        'consensus_lp': lp,
        'doe': doe
    }


def main():
    os.makedirs('/app/results', exist_ok=True)

    for ncb_path in sorted(globmod.glob('/app/data/*.ncb')):
        name = os.path.splitext(os.path.basename(ncb_path))[0]
        print(f"Processing {name}...")
        result = process_dataset(ncb_path)
        output_path = f'/app/results/{name}.json'
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"  consensus_dl = {result['consensus_dl']:.4f}")
        print(f"  tau = {result['tau']:.4f}")
        print(f"  Q = {result['cochran_q']:.2f}")
        print(f"  HKSJ CI = [{result['hksj_ci'][0]:.4f}, {result['hksj_ci'][1]:.4f}]")
        print(f"  LP mean = {result['consensus_lp']:.4f}")
        sig_labs = [lab for lab, d in result['doe'].items() if d['significant']]
        print(f"  Significant labs: {sig_labs if sig_labs else 'none'}")
        print(f"  Written to {output_path}")


if __name__ == '__main__':
    main()
