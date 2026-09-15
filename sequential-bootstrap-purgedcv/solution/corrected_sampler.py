"""Corrected bootstrap sampling with concurrency-aware sequential draws."""

import numpy as np
import pandas as pd


def build_indicator_matrix(bar_index, t1):
    """Build indicator matrix for label concurrency.

    indM[t, i] = 1.0 if bar t is within the lifespan of label i.
    """
    indM = pd.DataFrame(0.0, index=bar_index, columns=range(t1.shape[0]))
    for i, (start, end) in enumerate(t1.items()):
        indM.loc[start:end, i] = 1.0
    return indM


def get_avg_uniqueness(ind_matrix):
    """Average uniqueness from indicator matrix.

    Concurrency c_t = number of active labels at bar t.
    Uniqueness u_{t,i} = ind_matrix[t,i] / c_t.
    Average uniqueness of label i = mean of its non-zero uniqueness values.
    """
    c = ind_matrix.sum(axis=1)
    u = ind_matrix.div(c, axis=0)
    return u[u > 0].mean()


def seq_bootstrap(ind_matrix, n_samples=None, random_state=None):
    """Sequential bootstrap: draw samples weighted by conditional uniqueness.

    At each step, for every candidate column, compute its average uniqueness
    given the columns already drawn. Draw the next sample with probability
    proportional to these uniqueness values.
    """
    rng = np.random.RandomState(random_state)
    if n_samples is None:
        n_samples = ind_matrix.shape[1]
    phi = []
    while len(phi) < n_samples:
        avg_u = pd.Series(dtype=float)
        for i in ind_matrix.columns:
            sub = ind_matrix[phi + [i]]
            avg_u.loc[i] = get_avg_uniqueness(sub).iloc[-1]
        prob = avg_u / avg_u.sum()
        phi.append(rng.choice(ind_matrix.columns, p=prob.values))
    return phi


def sample_bootstrap(ind_matrix, n_samples=None, seed=42):
    """Original random bootstrap — kept for baseline comparison."""
    rng = np.random.RandomState(seed)
    n_cols = ind_matrix.shape[1]
    if n_samples is None:
        n_samples = n_cols
    return list(rng.choice(n_cols, size=n_samples, replace=True))


def compute_uniqueness(ind_matrix, samples):
    """Compute average uniqueness of selected samples."""
    sub = ind_matrix[samples]
    c = sub.sum(axis=1)
    c = c.replace(0, 1)
    u = sub.div(c, axis=0)
    avg_u = u[u > 0].mean()
    return float(avg_u.mean())
