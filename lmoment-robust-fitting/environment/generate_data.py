#!/usr/bin/env python3
"""Generate synthetic extreme value datasets for analysis task."""
import os
import numpy as np
from scipy import stats

os.makedirs('/app/data', exist_ok=True)

rng = np.random.default_rng(42)

# Univariate dataset: GEV(c=-0.3, loc=100, scale=30) with ~3% outlier contamination
n = 500
n_contaminated = 15
n_clean = n - n_contaminated

clean = stats.genextreme.rvs(
    c=-0.3, loc=100, scale=30, size=n_clean, random_state=rng
)
# Outlier contamination: shifted measurements centered above the 95th percentile
# (~159) of the true GEV but within its support (upper bound = 200).
# These inflict noticeable bias on ordinary moment estimators while remaining
# within the distribution support so that log-likelihood stays finite.
contaminated = rng.normal(loc=170, scale=5, size=n_contaminated)

data = np.concatenate([clean, contaminated])
shuffle_rng = np.random.default_rng(123)
shuffle_rng.shuffle(data)
np.savetxt('/app/data/annual_maxima.csv', data, fmt='%.10f')

# Bivariate dataset: GEV marginals via Gaussian copula with moderate correlation
n_biv = 200
z = rng.multivariate_normal([0, 0], [[1, 0.65], [0.65, 1]], size=n_biv)
u = np.clip(stats.norm.cdf(z), 0.001, 0.999)

x1 = stats.genextreme.ppf(u[:, 0], c=-0.15, loc=50, scale=15)
x2 = stats.genextreme.ppf(u[:, 1], c=-0.1, loc=30, scale=10)

biv = np.column_stack([x1, x2])
np.savetxt(
    '/app/data/bivariate.csv', biv, delimiter=',',
    fmt='%.10f', header='x1,x2', comments=''
)
