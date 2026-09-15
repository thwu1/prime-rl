"""Cross-validation module for model evaluation."""

from sklearn.model_selection import KFold
from sklearn.metrics import log_loss
import numpy as np


def cross_validate(clf, X, y, n_splits=5, seed=42):
    """Evaluate classifier performance using cross-validation.

    Uses k-fold splitting to estimate out-of-sample performance.
    """
    cv = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    scores = []
    for train_idx, test_idx in cv.split(X):
        clf.fit(X.iloc[train_idx], y.iloc[train_idx])
        prob = clf.predict_proba(X.iloc[test_idx])
        score = -log_loss(y.iloc[test_idx], prob, labels=clf.classes_)
        scores.append(score)
    return float(np.mean(scores))
