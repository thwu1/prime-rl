#!/usr/bin/env python3
"""Corrected pipeline entry point — compares original vs corrected evaluation."""

import json
import sys
import tomllib
import sqlite3
import numpy as np
import pandas as pd

sys.path.insert(0, '/app')

from sklearn.ensemble import RandomForestClassifier
from pipeline.data_generator import generate_dataset
from pipeline.evaluator import cross_validate, cross_validate_purged
from pipeline.sampler import (
    build_indicator_matrix, sample_bootstrap, seq_bootstrap,
    compute_uniqueness, get_avg_uniqueness
)
from pipeline.importance import compute_mdi_importance


def load_config():
    """Load configuration from TOML file and SQLite database."""
    with open('/app/config.toml', 'rb') as f:
        cfg = tomllib.load(f)
    conn = sqlite3.connect('/app/meta/pipeline.db')
    params = dict(conn.execute("SELECT key, value FROM params").fetchall())
    conn.close()
    return cfg, params


def main():
    cfg, params = load_config()

    seed = int(params['seed'])
    n_samples_val = int(params['n_samples'])
    ar_coef = float(params['ar_coefficient'])
    label_horizon = int(params['label_horizon'])
    n_informative = int(params['n_informative'])
    n_redundant = int(params['n_redundant'])
    n_noise = int(params['n_noise'])

    X, y, t1, feature_names = generate_dataset(
        seed, n_samples_val, ar_coef, label_horizon,
        n_informative, n_redundant, n_noise
    )

    clf = RandomForestClassifier(
        n_estimators=cfg['model']['n_estimators'],
        max_depth=cfg['model']['max_depth'],
        criterion=cfg['model']['criterion'],
        random_state=seed,
        n_jobs=1
    )

    # --- Original (flawed) evaluation ---
    original_score = cross_validate(
        clf, X, y, n_splits=cfg['evaluation']['n_splits'], seed=seed
    )

    # --- Corrected evaluation with purging and embargo ---
    corrected_score = cross_validate_purged(
        clf, X, y, t1, n_splits=cfg['evaluation']['n_splits'], pct_embargo=0.10
    )

    leakage_ratio = abs(corrected_score) / abs(original_score)

    # --- Sampling comparison ---
    # Use a canonical small example to demonstrate sequential vs random uniqueness
    t1_small = pd.Series([2, 3, 5], index=[0, 2, 4])
    bar_idx_small = range(t1_small.max() + 1)
    ind_small = build_indicator_matrix(bar_idx_small, t1_small)

    n_trials = 200
    seq_uniq = []
    rand_uniq = []
    for trial in range(n_trials):
        phi_seq = seq_bootstrap(ind_small, random_state=trial)
        seq_uniq.append(get_avg_uniqueness(ind_small[phi_seq]).mean())

        trial_rng = np.random.RandomState(trial)
        phi_rand = list(trial_rng.choice(ind_small.columns, size=ind_small.shape[1]))
        rand_uniq.append(get_avg_uniqueness(ind_small[phi_rand]).mean())

    # --- Feature importance ---
    clf.fit(X, y)
    importances = compute_mdi_importance(clf, feature_names)
    top10 = importances.nlargest(10).index.tolist()
    n_inf = sum(1 for f in top10 if f.startswith('I_'))

    results = {
        'original_cv_score': original_score,
        'corrected_cv_score': corrected_score,
        'leakage_ratio': leakage_ratio,
        'corrected_sampling_uniqueness': float(np.mean(seq_uniq)),
        'baseline_sampling_uniqueness': float(np.mean(rand_uniq)),
        'n_informative_in_top10': int(n_inf),
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
