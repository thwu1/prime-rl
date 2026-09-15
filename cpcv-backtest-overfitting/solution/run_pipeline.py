#!/usr/bin/env python3

"""
Combinatorial Purged Cross-Validation (CPCV) with
Probability of Backtest Overfitting (PBO) estimation.

Implements the CPCV framework from Lopez de Prado's research:
1. Divide observations into N contiguous groups
2. Generate all C(N,k) combinations of test groups
3. For each combination, purge training observations whose label
   intervals overlap test group intervals, and apply embargo
4. Train multiple strategies and compute IS/OOS performance
5. Estimate PBO from IS vs OOS performance comparison
"""

import numpy as np
import pandas as pd
import json
import os
from itertools import combinations
from math import comb
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import log_loss


def load_data():
    """Load features, labels, label end-times, and configuration."""
    X = pd.read_csv('/app/data/features.csv', index_col=0, parse_dates=True)

    y_df = pd.read_csv('/app/data/labels.csv', index_col=0, parse_dates=True)
    y = y_df.iloc[:, 0]

    t1_df = pd.read_csv('/app/data/t1.csv', index_col=0)
    t1_df.index = pd.to_datetime(t1_df.index)
    t1_df['t1'] = pd.to_datetime(t1_df['t1'])
    t1 = t1_df['t1']

    with open('/app/data/config.json') as f:
        config = json.load(f)

    return X, y, t1, config


def compute_cpcv_splits(n_obs, t1, n_groups, n_test_groups, pct_embargo):
    """
    Compute all C(n_groups, n_test_groups) train/test splits
    with purging and embargo.

    Purging: for each test group, remove any training observation
    whose label interval [obs_start, t1[obs]] overlaps the test
    group's interval [group_start_time, max(t1 in group)].

    Embargo: after each test group's last index, exclude the next
    embargo_size observations from training.
    """
    indices = np.arange(n_obs)
    embargo_size = int(n_obs * pct_embargo)
    groups = np.array_split(indices, n_groups)

    # Precompute datetime arrays for fast comparison
    idx_times = t1.index.values   # observation start times (datetime64)
    t1_times = t1.values          # label end times (datetime64)

    splits = []

    for test_combo in combinations(range(n_groups), n_test_groups):
        # Identify test and initial train indices
        test_idx = np.concatenate([groups[g] for g in test_combo])
        train_groups = [g for g in range(n_groups) if g not in test_combo]
        train_idx_initial = np.concatenate([groups[g] for g in train_groups])

        to_remove = set()

        # Purge: for each test group independently
        for g in test_combo:
            g_indices = groups[g]
            g_start = idx_times[g_indices[0]]
            g_t1_max = t1_times[g_indices].max()

            for i in train_idx_initial:
                obs_start = idx_times[i]
                obs_end = t1_times[i]
                # Interval overlap: [obs_start, obs_end] ∩ [g_start, g_t1_max]
                if obs_start <= g_t1_max and obs_end >= g_start:
                    to_remove.add(int(i))

        # Embargo: exclude observations after each test group boundary
        for g in test_combo:
            g_end = int(groups[g][-1]) + 1
            for j in range(g_end, min(g_end + embargo_size, n_obs)):
                to_remove.add(j)

        train_idx = sorted(int(i) for i in train_idx_initial
                           if int(i) not in to_remove)

        splits.append({
            'train': train_idx,
            'test': sorted(int(i) for i in test_idx),
            'test_groups': list(test_combo)
        })

    return splits


def compute_pbo(X_values, y_values, splits, max_depths, n_estimators,
                random_state):
    """
    Compute Probability of Backtest Overfitting (PBO).

    For each CPCV split, train M strategies (RF with different max_depth)
    and compute in-sample and out-of-sample negative log-loss.

    PBO = fraction of splits where the best in-sample strategy has
    OOS performance at or below the median OOS performance.
    """
    n_splits = len(splits)
    n_strategies = len(max_depths)

    is_scores = np.zeros((n_splits, n_strategies))
    oos_scores = np.zeros((n_splits, n_strategies))

    for split_idx, split in enumerate(splits):
        train_idx = split['train']
        test_idx = split['test']

        X_train = X_values[train_idx]
        y_train = y_values[train_idx]
        X_test = X_values[test_idx]
        y_test = y_values[test_idx]

        for strat_idx, max_depth in enumerate(max_depths):
            clf = RandomForestClassifier(
                n_estimators=n_estimators,
                max_depth=max_depth,
                random_state=random_state,
                criterion='entropy'
            )
            clf.fit(X_train, y_train)

            # In-sample negative log-loss (higher = better)
            is_prob = clf.predict_proba(X_train)
            is_scores[split_idx, strat_idx] = -log_loss(
                y_train, is_prob, labels=[0, 1]
            )

            # Out-of-sample negative log-loss
            oos_prob = clf.predict_proba(X_test)
            oos_scores[split_idx, strat_idx] = -log_loss(
                y_test, oos_prob, labels=[0, 1]
            )

        print(f"  Split {split_idx + 1}/{n_splits} done")

    # PBO: fraction of splits where best-IS strategy underperforms OOS
    overfit_count = 0
    for split_idx in range(n_splits):
        best_is_strat = np.argmax(is_scores[split_idx])
        oos_of_best = oos_scores[split_idx, best_is_strat]
        oos_median = np.median(oos_scores[split_idx])
        if oos_of_best <= oos_median:
            overfit_count += 1

    pbo = overfit_count / n_splits
    return pbo, n_splits, n_strategies


def main():
    print("Loading data...")
    X, y, t1, config = load_data()

    os.makedirs('/app/results', exist_ok=True)

    # Compute CPCV splits
    print(f"Computing CPCV splits: C({config['n_groups']}, "
          f"{config['n_test_groups']}) = "
          f"{comb(config['n_groups'], config['n_test_groups'])} combinations")

    splits = compute_cpcv_splits(
        n_obs=len(X),
        t1=t1,
        n_groups=config['n_groups'],
        n_test_groups=config['n_test_groups'],
        pct_embargo=config['pct_embargo']
    )

    with open('/app/results/cpcv_splits.json', 'w') as f:
        json.dump(splits, f)

    print(f"Generated {len(splits)} CPCV splits")
    for i, s in enumerate(splits):
        print(f"  Split {i}: train={len(s['train'])}, "
              f"test={len(s['test'])}, groups={s['test_groups']}")

    # Compute PBO
    print("\nComputing PBO...")
    max_depths = config['max_depths']
    pbo, n_splits, n_strategies = compute_pbo(
        X_values=X.values,
        y_values=y.values,
        splits=splits,
        max_depths=max_depths,
        n_estimators=config['n_estimators'],
        random_state=config['random_state']
    )

    pbo_result = {
        'pbo': float(pbo),
        'num_splits': n_splits,
        'num_strategies': n_strategies
    }

    with open('/app/results/pbo_result.json', 'w') as f:
        json.dump(pbo_result, f, indent=2)

    print(f"\nResults:")
    print(f"  CPCV splits: {n_splits}")
    print(f"  Strategies:  {n_strategies}")
    print(f"  PBO:         {pbo:.4f}")


if __name__ == '__main__':
    main()
