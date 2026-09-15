#!/usr/bin/env python3
"""Evaluate a custom proposal covariance for the correlated_8d target.

Reads /app/optimal_proposal.npy and measures mean meeting time.
Exits 0 if threshold met, 1 otherwise.

"""
import sys
import numpy as np
import scipy.stats as st

sys.path.insert(0, "/app")

np.random.seed(123)

from couplings import metropolis_hastings

try:
    proposal_cov = np.load("/app/optimal_proposal.npy")
except Exception as e:
    print(f"Error loading /app/optimal_proposal.npy: {e}")
    sys.exit(1)

if proposal_cov.shape != (8, 8):
    print(f"Expected shape (8, 8), got {proposal_cov.shape}")
    sys.exit(1)

dim = 8
cov = 0.3 * np.eye(dim) + 0.7 * np.ones((dim, dim))
rv = st.multivariate_normal(np.zeros(dim), cov)

data = metropolis_hastings(
    log_prob=rv.logpdf,
    proposal_cov=proposal_cov,
    init_x=4 * np.ones(dim),
    init_y=-4 * np.ones(dim),
    lag=1,
    iters=300,
    chains=64,
)

mean_mt = data.meeting_time.mean()
max_mt = data.meeting_time.max()
print(f"Meeting time: mean={mean_mt:.2f}, max={max_mt:.2f}")

THRESHOLD = 50
if mean_mt <= THRESHOLD:
    print(f"PASS: {mean_mt:.2f} <= {THRESHOLD}")
    sys.exit(0)
else:
    print(f"FAIL: {mean_mt:.2f} > {THRESHOLD}")
    sys.exit(1)
