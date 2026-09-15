#!/usr/bin/env python3
"""
Solve the double pendulum parameter estimation problem.

Estimates 7 parameters (m2, l1, l2, b1, b2, qd1_0, qd2_0) given that m1 is
known from the config. Uses differential evolution for global search
followed by L-BFGS-B for local refinement.

The key insight is that in the Lagrangian formulation M*qdd = -C - G - D,
all terms (mass matrix M, Coriolis C, gravity G, damping D) are linear in
a common mass scale. Without fixing at least one mass, the parameters are
only identifiable up to a multiplicative factor. With m1 known, the scale
symmetry is broken and all remaining parameters become uniquely identifiable.
"""
import json
import sys
import numpy as np
from scipy.optimize import differential_evolution, minimize

sys.path.insert(0, '/app')
from simulator import simulate, load_config

# Load configuration and observed trajectory
config = load_config('/app/data/config.json')
with open('/app/data/trajectory.json') as f:
    observed = np.array(json.load(f))

g = config["g"]
dt = config["dt"]
n_steps = config["n_steps"]
q1_0 = config["q1_0"]
q2_0 = config["q2_0"]
m1 = config["m1"]  # Known mass of link 1


def cost(params):
    """Trajectory matching cost: MSE of joint positions over all timesteps."""
    m2, l1, l2, b1, b2, qd1_0, qd2_0 = params
    try:
        states = simulate(q1_0, q2_0, qd1_0, qd2_0,
                          m1, m2, l1, l2, b1, b2, g, dt, n_steps)
        sim = np.array(states)
        diff = sim[:, :2] - observed
        return np.mean(diff ** 2)
    except (OverflowError, ZeroDivisionError, ValueError, FloatingPointError):
        return 1e10


# Parameter bounds: [m2, l1, l2, b1, b2, qd1_0, qd2_0]
bounds = [
    (0.1, 3.0),    # m2
    (0.1, 2.0),    # l1
    (0.1, 2.0),    # l2
    (0.001, 0.5),  # b1
    (0.001, 0.5),  # b2
    (-3.0, 3.0),   # qd1_0
    (-3.0, 3.0),   # qd2_0
]

print("Phase 1: Differential evolution (global search)...")
result_de = differential_evolution(
    cost, bounds, seed=42, maxiter=500,
    tol=1e-12, atol=1e-14, polish=False,
    mutation=(0.5, 1.5), recombination=0.9,
    popsize=25, workers=1
)
print(f"  DE cost = {result_de.fun:.2e}")
print(f"  DE params = {result_de.x}")

print("Phase 2: L-BFGS-B (local refinement)...")
result = minimize(
    cost, result_de.x, method='L-BFGS-B',
    bounds=bounds, options={'maxiter': 2000, 'ftol': 1e-15}
)
print(f"  Refined cost = {result.fun:.2e}")
print(f"  Refined params = {result.x}")

# Extract parameters
m2, l1, l2, b1, b2, qd1_0, qd2_0 = result.x

estimated = {
    "m2": float(m2),
    "l1": float(l1),
    "l2": float(l2),
    "b1": float(b1),
    "b2": float(b2),
    "qd1_0": float(qd1_0),
    "qd2_0": float(qd2_0),
}

with open('/app/estimated_params.json', 'w') as f:
    json.dump(estimated, f, indent=2)

print("\nEstimated parameters:")
for k, v in estimated.items():
    print(f"  {k}: {v:.6f}")
