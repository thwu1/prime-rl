import numpy as np
import json

np.random.seed(42)

n = 5000
d = 50
sigma_kernel = 3.0
lam = 0.01

# Generate clustered data with unbalanced sizes.
# Unbalanced clusters create non-uniform leverage score distributions,
# making leverage-score-based landmark selection essential.
cluster_sizes = [1500, 1000, 800, 600, 400, 300, 200, 100, 50, 50]
assert sum(cluster_sizes) == n

X = np.zeros((n, d))
idx = 0
for i, size in enumerate(cluster_sizes):
    # Cluster centers well-separated in ambient space
    center = np.random.randn(d) * 8
    # Varying within-cluster spread: tighter clusters have higher
    # within-cluster kernel correlation, affecting leverage scores
    spread = 0.2 + 0.05 * i
    X[idx:idx + size] = center + np.random.randn(size, d) * spread
    idx += size

# Random target vector
y = np.random.randn(n) * 2.0

np.save('/app/data/X.npy', X)
np.save('/app/data/y.npy', y)

config = {
    "kernel": "rbf",
    "sigma": sigma_kernel,
    "lambda": lam,
    "n": n,
    "d": d,
    "min_landmarks": 100,
    "max_landmarks": 500,
    "max_cg_iterations": 200,
    "residual_tolerance": 1e-6
}
with open('/app/data/config.json', 'w') as f:
    json.dump(config, f, indent=2)

print(f"Generated data: X {X.shape}, y {y.shape}")
print(f"Cluster sizes: {cluster_sizes}")
print(f"Config: sigma={sigma_kernel}, lambda={lam}")
