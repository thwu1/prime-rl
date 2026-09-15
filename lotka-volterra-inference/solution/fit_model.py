#!/usr/bin/env python3
"""Fit ecological dynamics model to Hudson Bay pelt data using CmdStanPy.

"""

import json
import os
import glob
import numpy as np
import pandas as pd
import cmdstanpy


def find_col(df, candidates):
    """Find column name from candidates, handling CmdStan version differences."""
    for c in candidates:
        if c in df.columns:
            return c
    for c in df.columns:
        cl = c.lower().replace(' ', '_')
        for cand in candidates:
            if cand.lower() in cl:
                return c
    raise ValueError(f"None of {candidates} found in columns: {list(df.columns)}")


def ensure_cmdstan():
    """Locate CmdStan via env var or /opt search."""
    try:
        p = cmdstanpy.cmdstan_path()
        if os.path.isdir(p):
            print(f"Using CmdStan at: {p}")
            return
    except (ValueError, FileNotFoundError):
        pass

    for d in sorted(glob.glob('/opt/cmdstan-*'), reverse=True):
        if os.path.isfile(os.path.join(d, 'bin', 'stanc')):
            cmdstanpy.set_cmdstan_path(d)
            print(f"Found CmdStan at: {d}")
            return

    raise RuntimeError("CmdStan not found in /opt/")


def main():
    ensure_cmdstan()

    # ---- Read data ----
    data = pd.read_csv('/app/data/hudson_bay_pelts.csv')

    y_init = [float(data['hare'].iloc[0]), float(data['lynx'].iloc[0])]
    N = len(data) - 1  # 20
    y = []
    for i in range(1, len(data)):
        y.append([float(data['hare'].iloc[i]), float(data['lynx'].iloc[i])])
    ts = list(range(1, N + 1))

    N_pred = 10
    ts_pred = list(range(N + 1, N + N_pred + 1))

    stan_data = {
        'N': N,
        'ts': ts,
        'y_init': y_init,
        'y': y,
        'N_pred': N_pred,
        'ts_pred': ts_pred,
    }

    # ---- Compile model ----
    model = cmdstanpy.CmdStanModel(stan_file='/app/models/dynamics.stan')

    # ---- Initial values for better convergence ----
    rng = np.random.RandomState(42)
    inits = []
    for _ in range(4):
        inits.append({
            'theta': [
                float(rng.uniform(0.4, 0.7)),
                float(rng.uniform(0.02, 0.04)),
                float(rng.uniform(0.6, 1.0)),
                float(rng.uniform(0.02, 0.04)),
            ],
            'z_init': [
                float(rng.uniform(25, 40)),
                float(rng.uniform(3, 7)),
            ],
            'sigma': [
                float(rng.uniform(0.2, 0.35)),
                float(rng.uniform(0.2, 0.35)),
            ],
        })

    # ---- Fit ----
    fit = model.sample(
        data=stan_data,
        chains=4,
        parallel_chains=1,
        iter_warmup=1000,
        iter_sampling=1000,
        adapt_delta=0.9,
        max_treedepth=10,
        seed=42,
        inits=inits,
    )

    # ---- Extract summary with robust column detection ----
    summary = fit.summary()
    print(f"Summary columns: {list(summary.columns)}")

    mean_col = find_col(summary, ['Mean', 'mean'])
    q5_col = find_col(summary, ['5%', 'q5'])
    q95_col = find_col(summary, ['95%', 'q95'])
    rhat_col = find_col(summary, ['R_hat', 'Rhat', 'rhat'])
    ess_col = find_col(summary, ['ESS_bulk', 'N_Eff', 'Bulk_ESS', 'ess_bulk'])

    param_names = [
        'theta[1]', 'theta[2]', 'theta[3]', 'theta[4]',
        'z_init[1]', 'z_init[2]',
        'sigma[1]', 'sigma[2]',
    ]

    results = {'parameters': {}, 'diagnostics': {}}

    for p in param_names:
        row = summary.loc[p]
        results['parameters'][p] = {
            'mean': float(row[mean_col]),
            'q5': float(row[q5_col]),
            'q95': float(row[q95_col]),
            'rhat': float(row[rhat_col]),
            'ess_bulk': float(row[ess_col]),
        }

    # ---- Divergent transitions ----
    draws = fit.draws_pd()
    if 'divergent__' in draws.columns:
        total_divergent = int(draws['divergent__'].sum())
    else:
        total_divergent = 0

    all_rhats = [results['parameters'][p]['rhat'] for p in param_names]
    all_ess = [results['parameters'][p]['ess_bulk'] for p in param_names]

    results['diagnostics'] = {
        'total_divergent_transitions': total_divergent,
        'max_rhat': float(max(all_rhats)),
        'min_ess_bulk': float(min(all_ess)),
    }

    # ---- Save posterior summary ----
    os.makedirs('/app/results', exist_ok=True)
    with open('/app/results/posterior_summary.json', 'w') as f:
        json.dump(results, f, indent=2)

    # ---- Posterior predictive CSV ----
    pp_rows = []
    for n in range(1, N + 1):
        year = 1900 + n
        hare_draws = draws[f'y_rep[{n},1]']
        lynx_draws = draws[f'y_rep[{n},2]']
        pp_rows.append({
            'year': year,
            'hare_mean': float(hare_draws.mean()),
            'hare_q5': float(hare_draws.quantile(0.05)),
            'hare_q95': float(hare_draws.quantile(0.95)),
            'lynx_mean': float(lynx_draws.mean()),
            'lynx_q5': float(lynx_draws.quantile(0.05)),
            'lynx_q95': float(lynx_draws.quantile(0.95)),
        })
    pd.DataFrame(pp_rows).to_csv('/app/results/posterior_predictive.csv', index=False)

    # ---- Forward predictions CSV ----
    pred_rows = []
    for n in range(1, N_pred + 1):
        year = 1920 + n
        hare_draws = draws[f'y_pred[{n},1]']
        lynx_draws = draws[f'y_pred[{n},2]']
        pred_rows.append({
            'year': year,
            'hare_mean': float(hare_draws.mean()),
            'hare_q5': float(hare_draws.quantile(0.05)),
            'hare_q95': float(hare_draws.quantile(0.95)),
            'lynx_mean': float(lynx_draws.mean()),
            'lynx_q5': float(lynx_draws.quantile(0.05)),
            'lynx_q95': float(lynx_draws.quantile(0.95)),
        })
    pd.DataFrame(pred_rows).to_csv('/app/results/predictions.csv', index=False)

    # ---- Report ----
    print("\n=== Results ===")
    for p in param_names:
        d = results['parameters'][p]
        print(f"  {p:12s}  mean={d['mean']:.4f}  [{d['q5']:.4f}, {d['q95']:.4f}]  "
              f"R-hat={d['rhat']:.3f}  ESS={d['ess_bulk']:.0f}")
    print(f"\n  Divergent transitions: {total_divergent}")
    print(f"  Max R-hat: {max(all_rhats):.4f}")
    print(f"  Min ESS:   {min(all_ess):.1f}")
    print("\nAll results saved to /app/results/")


if __name__ == '__main__':
    main()
