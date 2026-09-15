"""Tile sampling module."""

import numpy as np


def stratified_sample(features, n, seed=None):
    features = np.asarray(features, dtype=float)
    n_tiles = features.shape[0]
    if n >= n_tiles:
        return np.arange(n_tiles)
    return np.arange(n)
