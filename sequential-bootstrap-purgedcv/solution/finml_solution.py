#!/usr/bin/env python3
"""
Financial ML Anti-Leakage Pipeline

Implements sequential bootstrap, PurgedKFold cross-validation, and a
comparison pipeline demonstrating information leakage in naive CV on
autocorrelated financial time-series data.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import KFold
from sklearn.metrics import log_loss
import json


def get_indicator_matrix(bar_index, t1):
    """Build binary indicator matrix.

    indM[t, i] = 1.0 if bar t is within the label lifespan
    [t1.index[i], t1.iloc[i]] (inclusive).
    """
    indM = pd.DataFrame(0.0, index=bar_index, columns=range(t1.shape[0]))
    for i, (t0, t1_val) in enumerate(t1.items()):
        indM.loc[t0:t1_val, i] = 1.0
    return indM


def get_avg_uniqueness(ind_matrix):
    """Average uniqueness from indicator matrix.

    Concurrency c_t = number of active labels at bar t.
    Uniqueness u_{t,i} = ind_matrix[t,i] / c_t.
    Average uniqueness of label i = mean of non-zero u_{t,i}.
    """
    c = ind_matrix.sum(axis=1)  # concurrency per bar
    u = ind_matrix.div(c, axis=0)  # uniqueness per bar/label
    avgU = u[u > 0].mean()  # average uniqueness per label (ignores NaN/0)
    return avgU


def seq_bootstrap(ind_matrix, n_samples=None, random_state=None):
    """Sequential bootstrap: draw samples weighted by average uniqueness.

    At each step, compute the conditional average uniqueness of each
    candidate given the samples already drawn, and draw with probability
    proportional to that uniqueness.
    """
    rng = np.random.RandomState(random_state)
    if n_samples is None:
        n_samples = ind_matrix.shape[1]
    phi = []
    while len(phi) < n_samples:
        avgU = pd.Series(dtype=float)
        for i in ind_matrix.columns:
            indM_ = ind_matrix[phi + [i]]
            avgU.loc[i] = get_avg_uniqueness(indM_).iloc[-1]
        prob = avgU / avgU.sum()
        phi.append(rng.choice(ind_matrix.columns, p=prob.values))
    return phi


class PurgedKFold:
    """K-fold cross-validation with purging of overlapping labels and embargo.

    Test sets are contiguous index slices. Training observations whose
    label spans overlap with the test set time range are removed (purged).
    An optional embargo removes additional observations after the purge
    boundary.
    """

    def __init__(self, n_splits=3, t1=None, pct_embargo=0.0):
        if not isinstance(t1, pd.Series):
            raise ValueError('t1 must be a pd.Series')
        self.n_splits = n_splits
        self.t1 = t1
        self.pct_embargo = pct_embargo

    def get_n_splits(self, X=None, y=None, groups=None):
        return self.n_splits

    def split(self, X, y=None, groups=None):
        if (X.index == self.t1.index).sum() != len(self.t1):
            raise ValueError('X and t1 must have the same index')

        indices = np.arange(X.shape[0])
        mbrg = int(X.shape[0] * self.pct_embargo)
        test_starts = [
            (s[0], s[-1] + 1)
            for s in np.array_split(indices, self.n_splits)
        ]

        for i, j in test_starts:
            t0 = self.t1.index[i]  # start index value of test set
            test_indices = indices[i:j]

            # Position where max t1 of test observations falls in the index
            maxT1Idx = self.t1.index.searchsorted(
                self.t1.iloc[test_indices].max()
            )

            # Left train: observations whose labels end at or before test start
            left_mask = self.t1 <= t0
            train_left = self.t1.index.searchsorted(
                self.t1[left_mask].index
            )

            # Right train: observations at positions >= maxT1Idx + embargo
            if maxT1Idx < X.shape[0]:
                train_right = indices[maxT1Idx + mbrg:]
            else:
                train_right = np.array([], dtype=int)

            train_indices = np.concatenate((train_left, train_right))

            # Ensure no test indices leaked into training
            train_indices = np.setdiff1d(train_indices, test_indices)

            yield train_indices, test_indices


def run_pipeline(seed=42):
    """Run the full anti-leakage pipeline.

    1. Compare sequential vs random bootstrap uniqueness.
    2. Generate autocorrelated synthetic data with forward-looking labels.
    3. Compare purged vs naive cross-validation.
    4. Compute MDI feature importances.
    """
    rng = np.random.RandomState(seed)

    # --- Part 1: Sequential bootstrap comparison ---
    t1_small = pd.Series([2, 3, 5], index=[0, 2, 4])
    bar_index_small = range(t1_small.max() + 1)
    indM_small = get_indicator_matrix(bar_index_small, t1_small)

    n_trials = 200
    seq_uniq_list = []
    rand_uniq_list = []
    for trial in range(n_trials):
        phi_seq = seq_bootstrap(indM_small, random_state=trial)
        seq_uniq_list.append(get_avg_uniqueness(indM_small[phi_seq]).mean())

        trial_rng = np.random.RandomState(trial)
        phi_rand = list(trial_rng.choice(indM_small.columns,
                                         size=indM_small.shape[1]))
        rand_uniq_list.append(get_avg_uniqueness(indM_small[phi_rand]).mean())

    seq_avg_u = float(np.mean(seq_uniq_list))
    rand_avg_u = float(np.mean(rand_uniq_list))

    # --- Part 2: Generate synthetic autocorrelated data ---
    n = 2000
    n_informative = 10
    n_redundant = 10
    n_noise = 20
    span = 10  # label horizon

    # AR(1) signal with high persistence
    ar_coef = 0.98
    signal = np.zeros(n)
    for i in range(1, n):
        signal[i] = ar_coef * signal[i - 1] + rng.randn() * 0.1

    # Informative features: signal + lagged values
    X_inf = np.zeros((n, n_informative))
    X_inf[:, 0] = signal
    for j in range(1, n_informative):
        X_inf[j:, j] = signal[:-j]

    # Redundant features: linear combinations of informative
    X_red = np.zeros((n, n_redundant))
    for j in range(n_redundant):
        w = rng.randn(n_informative)
        X_red[:, j] = X_inf @ w + rng.randn(n) * 0.01

    # Noise features: IID Gaussian
    X_noise = rng.randn(n, n_noise)

    X_data = np.hstack([X_inf, X_red, X_noise])

    # Forward-looking labels: sign of return over 'span' bars
    forward_ret = np.zeros(n)
    for i in range(n - span):
        forward_ret[i] = signal[i + span] - signal[i]
    y_data = (forward_ret > 0).astype(int)

    # Build DataFrames with DatetimeIndex
    dates = pd.bdate_range(end='2024-01-01', periods=n)
    feature_names = (
        ['I_%d' % i for i in range(n_informative)]
        + ['R_%d' % i for i in range(n_redundant)]
        + ['N_%d' % i for i in range(n_noise)]
    )
    X = pd.DataFrame(X_data, index=dates, columns=feature_names)
    y = pd.Series(y_data, index=dates)

    # t1: each label's outcome depends on data up to 'span' bars ahead
    t1 = pd.Series(
        [dates[min(i + span, n - 1)] for i in range(n)],
        index=dates
    )

    # --- Part 3: Purged vs Naive CV ---
    clf = RandomForestClassifier(
        n_estimators=100, criterion='entropy', max_depth=5,
        random_state=seed, n_jobs=1
    )

    # Purged 5-fold CV with 1% embargo
    pkf = PurgedKFold(n_splits=5, t1=t1, pct_embargo=0.01)
    purged_scores = []
    for train_idx, test_idx in pkf.split(X):
        if len(train_idx) < 2:
            continue
        clf.fit(X.iloc[train_idx], y.iloc[train_idx])
        prob = clf.predict_proba(X.iloc[test_idx])
        score = -log_loss(y.iloc[test_idx], prob, labels=clf.classes_)
        purged_scores.append(score)
    purged_cv = float(np.mean(purged_scores))

    # Naive shuffled 5-fold CV
    naive_gen = KFold(n_splits=5, shuffle=True, random_state=seed)
    naive_scores = []
    for train_idx, test_idx in naive_gen.split(X):
        clf.fit(X.iloc[train_idx], y.iloc[train_idx])
        prob = clf.predict_proba(X.iloc[test_idx])
        score = -log_loss(y.iloc[test_idx], prob, labels=clf.classes_)
        naive_scores.append(score)
    naive_cv = float(np.mean(naive_scores))

    # --- Part 4: Feature importance (MDI) ---
    clf.fit(X, y)
    importances = pd.Series(clf.feature_importances_, index=feature_names)
    top10 = importances.nlargest(10).index.tolist()
    n_inf_in_top10 = sum(1 for f in top10 if f.startswith('I_'))

    # --- Write results ---
    results = {
        'seq_avg_uniqueness': seq_avg_u,
        'rand_avg_uniqueness': rand_avg_u,
        'purged_cv_neg_log_loss': purged_cv,
        'naive_cv_neg_log_loss': naive_cv,
        'n_informative_in_top10': int(n_inf_in_top10),
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    return results


if __name__ == '__main__':
    results = run_pipeline()
    print(json.dumps(results, indent=2))
