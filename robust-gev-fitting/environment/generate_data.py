#!/usr/bin/env python3
"""Generate synthetic flood peak data with outlier contamination."""
import numpy as np
from scipy.stats import genextreme

rng = np.random.default_rng(seed=77)
n_total = 2000
n_contam = 100

# True GEV: shape(c)=-0.05, loc=100, scale=30
clean = genextreme.rvs(
    c=-0.05, loc=100, scale=30,
    size=n_total - n_contam, random_state=rng
)

# Contamination: additive exponential shift on a subset of clean samples
# Simulates sensor malfunction adding positive bias
contam = clean[:n_contam] + rng.exponential(150, size=n_contam)

data = np.concatenate([clean[n_contam:], contam])
rng.shuffle(data)
np.save('/app/data.npy', data)
