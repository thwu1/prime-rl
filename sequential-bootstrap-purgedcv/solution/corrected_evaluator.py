"""Corrected cross-validation with temporal purging and embargo."""

from sklearn.model_selection import KFold
from sklearn.metrics import log_loss
import numpy as np
import pandas as pd


def cross_validate(clf, X, y, n_splits=5, seed=42):
    """Original (flawed) CV with shuffled KFold — kept for comparison."""
    cv = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    scores = []
    for train_idx, test_idx in cv.split(X):
        clf.fit(X.iloc[train_idx], y.iloc[train_idx])
        prob = clf.predict_proba(X.iloc[test_idx])
        score = -log_loss(y.iloc[test_idx], prob, labels=clf.classes_)
        scores.append(score)
    return float(np.mean(scores))


class PurgedKFold:
    """K-fold CV that purges training observations with overlapping labels
    and applies an embargo buffer after the test set."""

    def __init__(self, n_splits=5, t1=None, pct_embargo=0.10):
        if not isinstance(t1, pd.Series):
            raise ValueError('t1 must be a pd.Series')
        self.n_splits = n_splits
        self.t1 = t1
        self.pct_embargo = pct_embargo

    def split(self, X, y=None, groups=None):
        if (X.index == self.t1.index).sum() != len(self.t1):
            raise ValueError('X and t1 must have the same index')

        indices = np.arange(X.shape[0])
        mbrg = int(X.shape[0] * self.pct_embargo)
        test_ranges = [
            (s[0], s[-1] + 1)
            for s in np.array_split(indices, self.n_splits)
        ]

        for i, j in test_ranges:
            test_indices = indices[i:j]
            t0 = self.t1.index[i]  # start of test set

            # Find where the max label end of test observations falls
            max_t1_idx = self.t1.index.searchsorted(
                self.t1.iloc[test_indices].max()
            )

            # Left train: observations whose labels end at or before test start
            left_mask = self.t1 <= t0
            train_left = self.t1.index.searchsorted(self.t1[left_mask].index)

            # Right train: observations starting after max test label end + embargo
            if max_t1_idx < X.shape[0]:
                train_right = indices[max_t1_idx + mbrg:]
            else:
                train_right = np.array([], dtype=int)

            train_indices = np.concatenate((train_left, train_right))
            train_indices = np.setdiff1d(train_indices, test_indices)

            yield train_indices, test_indices


def cross_validate_purged(clf, X, y, t1, n_splits=5, pct_embargo=0.10):
    """Purged cross-validation with embargo."""
    pkf = PurgedKFold(n_splits=n_splits, t1=t1, pct_embargo=pct_embargo)
    scores = []
    for train_idx, test_idx in pkf.split(X):
        if len(train_idx) < 2:
            continue
        clf.fit(X.iloc[train_idx], y.iloc[train_idx])
        prob = clf.predict_proba(X.iloc[test_idx])
        score = -log_loss(y.iloc[test_idx], prob, labels=clf.classes_)
        scores.append(score)
    return float(np.mean(scores))
