"""Bootstrap sampling utilities for handling label concurrency."""

import numpy as np
import pandas as pd


def build_indicator_matrix(bar_index, t1):
    """Build indicator matrix showing which bars belong to which labels.

    Returns DataFrame where indM[t, i] = 1.0 if bar t is within the
    lifespan of label i (from t1.index[i] to t1.iloc[i]).
    """
    indM = pd.DataFrame(0.0, index=bar_index, columns=range(t1.shape[0]))
    for i, (start, end) in enumerate(t1.items()):
        indM.loc[start:end, i] = 1.0
    return indM


def sample_bootstrap(ind_matrix, n_samples=None, seed=42):
    """Draw bootstrap samples.

    Currently uses uniform random sampling with replacement.
    """
    rng = np.random.RandomState(seed)
    n_cols = ind_matrix.shape[1]
    if n_samples is None:
        n_samples = n_cols
    return list(rng.choice(n_cols, size=n_samples, replace=True))


def compute_uniqueness(ind_matrix, samples):
    """Compute average uniqueness of selected samples.

    Uniqueness measures how much each sample overlaps with others
    in the selection, based on the indicator matrix.
    At each bar t, concurrency c_t is the sum of active labels.
    Uniqueness of label i at bar t is indM[t,i] / c_t.
    Average uniqueness of label i is the mean of its non-zero uniqueness values.
    """
    sub = ind_matrix[samples]
    c = sub.sum(axis=1)
    c = c.replace(0, 1)  # avoid division by zero
    u = sub.div(c, axis=0)
    avg_u = u[u > 0].mean()
    return float(avg_u.mean())
