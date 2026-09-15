#!/usr/bin/env python3
"""

Generate a small CSV dataset (N=1000) for cachegrind profiling.
"""
import numpy as np
import os

SEED = 99
N_SMALL = 1000
P = 5
BETA_TRUE = np.array([1.5, -2.0, 0.5, 3.0, -1.0])
NOISE_STD = 0.5

rng = np.random.default_rng(SEED)
X = rng.standard_normal((N_SMALL, P))
noise = rng.standard_normal(N_SMALL) * NOISE_STD
y = X @ BETA_TRUE + noise
timestamps = np.sort(rng.uniform(0.0, 10.0, N_SMALL))
weights = np.abs(rng.standard_normal(N_SMALL)) + 0.1

os.makedirs("/app/data", exist_ok=True)
with open("/app/data/input.csv", "w") as f:
    f.write("f0,f1,f2,f3,f4,timestamp,weight,target\n")
    for i in range(N_SMALL):
        vals = [f"{X[i, j]:.17g}" for j in range(P)]
        vals.append(f"{timestamps[i]:.17g}")
        vals.append(f"{weights[i]:.17g}")
        vals.append(f"{y[i]:.17g}")
        f.write(",".join(vals) + "\n")

print(f"Generated profiling dataset with {N_SMALL} records at /app/data/input.csv")
