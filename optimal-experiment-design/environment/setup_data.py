#!/usr/bin/env python3
"""Generate deterministic experiment design data."""
import numpy as np
import json
import os

os.makedirs('/app', exist_ok=True)

np.random.seed(2024)
d = 5
m = 20

# Generate candidate experiment vectors with varying magnitudes
V = np.random.randn(m, d)
# Scale rows to have diverse norms (important for nontrivial A-criterion behavior)
scales = np.random.uniform(0.5, 2.5, size=m)
V = V * scales[:, None]

np.save('/app/experiments.npy', V)

config = {
    "dimension": d,
    "num_experiments": m,
    "budget": 30,
    "max_per_experiment": 8,
    "output_file": "/app/results.json"
}
with open('/app/config.json', 'w') as f:
    json.dump(config, f, indent=2)
