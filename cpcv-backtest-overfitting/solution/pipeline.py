#!/usr/bin/env python3

"""
Leakage-free backtesting pipeline with overfitting detection.
Reads data from SQLite, config from YAML, implements combinatorial
purged cross-validation with embargo, and computes PBO.
"""

import sqlite3
import yaml
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import log_loss
from itertools import combinations
import json
import os


def load_config(path='/app/data/config.yaml'):
    with open(path) as f:
        raw = yaml.safe_load(f)
    return {
        'n_groups': raw['cross_validation']['n_groups'],
        'n_test_groups': raw['cross_validation']['n_test_groups'],
        'pct_embargo': raw['cross_validation']['pct_embargo'],
        'max_depths': raw['classifier']['max_depths'],
        'n_estimators': raw['classifier']['n_estimators'],
        'random_state': raw['random_state'],
    }


def load_data(db_path='/app/data/market.db'):
    conn = sqlite3.connect(db_path)

    # Features
    md = pd.read_sql_query(
        'SELECT * FROM market_data ORDER BY obs_id', conn
    )
    feature_cols = [c for c in md.columns if c.startswith('f')]
    X = md[feature_cols].values

    # Labels
    labels = pd.read_sql_query(
        'SELECT obs_id, signal FROM signals ORDER BY obs_id', conn
    )
    y = labels['signal'].values

    # Event windows
    ew = pd.read_sql_query(
        'SELECT obs_id, event_start, event_end FROM event_windows ORDER BY obs_id',
        conn
    )
    conn.close()

    event_starts = pd.to_datetime(ew['event_start']).values
    event_ends = pd.to_datetime(ew['event_end']).values

    return X, y, event_starts, event_ends


def generate_cpcv_splits(n, event_starts, event_ends, n_groups, n_test_groups,
                         pct_embargo):
    """Generate combinatorial purged cross-validation splits."""
    indices = np.arange(n)
    groups = np.array_split(indices, n_groups)
    all_combos = list(combinations(range(n_groups), n_test_groups))
    embargo_size = int(n * pct_embargo)

    splits = []
    for combo in all_combos:
        # Test indices
        test_indices = np.sort(np.concatenate([groups[g] for g in combo]))

        # Determine test time span per test group
        test_group_spans = []
        for g in combo:
            g_idx = groups[g]
            g_start = event_starts[g_idx[0]]
            g_end = event_ends[g_idx].max()
            test_group_spans.append((g_start, g_end))

        # Start with all non-test observations as candidates
        train_mask = np.ones(n, dtype=bool)
        train_mask[test_indices] = False

        # Purge: remove training obs whose event windows overlap test time spans
        for g_start, g_end in test_group_spans:
            candidates = np.where(train_mask)[0]
            for i in candidates:
                if event_starts[i] <= g_end and event_ends[i] >= g_start:
                    train_mask[i] = False

        # Embargo: exclude observations immediately after each test group
        for g in combo:
            g_last = int(groups[g][-1]) + 1
            for j in range(g_last, min(g_last + embargo_size, n)):
                train_mask[j] = False

        train_indices = np.sort(np.where(train_mask)[0])

        splits.append({
            'train': train_indices.tolist(),
            'test': test_indices.tolist(),
            'test_groups': list(combo)
        })

    return splits


def evaluate_strategies(X, y, splits, max_depths, n_estimators, random_state):
    """Train RF classifiers for each depth and compute IS/OOS log-loss."""
    n_splits = len(splits)
    n_strategies = len(max_depths)
    is_scores = np.zeros((n_splits, n_strategies))
    oos_scores = np.zeros((n_splits, n_strategies))

    for si, split in enumerate(splits):
        train_idx = split['train']
        test_idx = split['test']
        X_train, y_train = X[train_idx], y[train_idx]
        X_test, y_test = X[test_idx], y[test_idx]

        for di, depth in enumerate(max_depths):
            clf = RandomForestClassifier(
                n_estimators=n_estimators,
                max_depth=depth,
                random_state=random_state,
            )
            clf.fit(X_train, y_train)

            prob_train = clf.predict_proba(X_train)
            is_scores[si, di] = -log_loss(
                y_train, prob_train, labels=clf.classes_
            )

            prob_test = clf.predict_proba(X_test)
            oos_scores[si, di] = -log_loss(
                y_test, prob_test, labels=clf.classes_
            )

    return is_scores, oos_scores


def compute_pbo(is_scores, oos_scores):
    """Probability of backtest overfitting: fraction of splits where
    the best in-sample strategy has OOS performance <= median OOS."""
    n_splits = is_scores.shape[0]
    overfit_count = 0
    for si in range(n_splits):
        best_is = np.argmax(is_scores[si])
        oos_of_best = oos_scores[si, best_is]
        median_oos = np.median(oos_scores[si])
        if oos_of_best <= median_oos:
            overfit_count += 1
    return overfit_count / n_splits


def main():
    cfg = load_config()
    X, y, event_starts, event_ends = load_data()
    n = len(y)

    splits = generate_cpcv_splits(
        n, event_starts, event_ends,
        cfg['n_groups'], cfg['n_test_groups'], cfg['pct_embargo']
    )

    os.makedirs('/app/results', exist_ok=True)
    with open('/app/results/cpcv_splits.json', 'w') as f:
        json.dump(splits, f)

    is_scores, oos_scores = evaluate_strategies(
        X, y, splits,
        cfg['max_depths'], cfg['n_estimators'], cfg['random_state']
    )

    pbo = compute_pbo(is_scores, oos_scores)

    pbo_result = {
        'pbo': float(pbo),
        'num_splits': len(splits),
        'num_strategies': len(cfg['max_depths']),
    }
    with open('/app/results/pbo_result.json', 'w') as f:
        json.dump(pbo_result, f)

    print(f"Done: {len(splits)} splits, {len(cfg['max_depths'])} strategies, "
          f"PBO={pbo:.4f}")


if __name__ == '__main__':
    main()
