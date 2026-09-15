#!/usr/bin/env python3
"""Pipeline entry point. Evaluates a classifier on synthetic financial data."""

import json
import sys
import tomllib
import sqlite3
import numpy as np

sys.path.insert(0, '/app')

from sklearn.ensemble import RandomForestClassifier
from pipeline.data_generator import generate_dataset
from pipeline.evaluator import cross_validate
from pipeline.sampler import build_indicator_matrix, sample_bootstrap, compute_uniqueness
from pipeline.importance import compute_mdi_importance


def load_config():
    """Load configuration from TOML file and SQLite database."""
    with open('/app/config.toml', 'rb') as f:
        cfg = tomllib.load(f)

    conn = sqlite3.connect('/app/meta/pipeline.db')
    cursor = conn.cursor()
    params = dict(cursor.execute("SELECT key, value FROM params").fetchall())
    conn.close()

    return cfg, params


def main():
    cfg, params = load_config()

    seed = int(params['seed'])
    n_samples = int(params['n_samples'])
    ar_coef = float(params['ar_coefficient'])
    label_horizon = int(params['label_horizon'])
    n_informative = int(params['n_informative'])
    n_redundant = int(params['n_redundant'])
    n_noise = int(params['n_noise'])

    X, y, t1, feature_names = generate_dataset(
        seed, n_samples, ar_coef, label_horizon,
        n_informative, n_redundant, n_noise
    )

    clf = RandomForestClassifier(
        n_estimators=cfg['model']['n_estimators'],
        max_depth=cfg['model']['max_depth'],
        criterion=cfg['model']['criterion'],
        random_state=seed,
        n_jobs=1
    )

    # Cross-validation
    cv_score = cross_validate(
        clf, X, y, n_splits=cfg['evaluation']['n_splits'], seed=seed
    )

    # Bootstrap sampling & uniqueness
    ind_matrix = build_indicator_matrix(X.index, t1)
    samples = sample_bootstrap(ind_matrix, seed=seed)
    uniqueness = compute_uniqueness(ind_matrix, samples)

    # Feature importance
    clf.fit(X, y)
    importances = compute_mdi_importance(clf, feature_names)
    top10 = importances.nlargest(10).index.tolist()
    n_inf = sum(1 for f in top10 if f.startswith('I_'))

    results = {
        'cv_score': cv_score,
        'sampling_uniqueness': uniqueness,
        'n_informative_in_top10': int(n_inf),
        'n_features': len(feature_names),
        'n_samples': n_samples,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
