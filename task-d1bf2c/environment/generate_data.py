#!/usr/bin/env python3
"""Generate observation data for the model selection task.
This script runs during Docker build only and is NOT available to the agent.
"""
import csv
import os
import numpy as np
from scipy.integrate import solve_ivp

# Ground truth system parameters
A, B, C, D = 0.55, 0.028, 0.80, 0.024
Y0 = [30.0, 10.0]
T_END = 25.0
NOISE_STD = 0.5
SEED = 12345


def rhs(t, y):
    return [A * y[0] - B * y[0] * y[1],
            -C * y[1] + D * y[0] * y[1]]


# 40 uniformly spaced observation times from 0.625 to 25.0
t_obs = np.linspace(0.625, 25.0, 40)

# High-accuracy ODE solution
sol = solve_ivp(rhs, [0.0, T_END], Y0, method='DOP853',
                t_eval=t_obs, rtol=1e-12, atol=1e-14)
assert sol.status == 0, f"ODE solver failed: {sol.message}"

# Add Gaussian observation noise
rng = np.random.default_rng(SEED)
y1_noisy = sol.y[0] + rng.normal(0, NOISE_STD, len(t_obs))
y2_noisy = sol.y[1] + rng.normal(0, NOISE_STD, len(t_obs))

# Write CSV
os.makedirs('/app/data', exist_ok=True)
with open('/app/data/observations.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['t', 'y1', 'y2'])
    for i in range(len(t_obs)):
        writer.writerow([f'{t_obs[i]:.6f}', f'{y1_noisy[i]:.6f}', f'{y2_noisy[i]:.6f}'])

print(f"Generated {len(t_obs)} observations -> /app/data/observations.csv")
