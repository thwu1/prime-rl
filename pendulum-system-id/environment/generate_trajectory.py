#!/usr/bin/env python3
"""Generate observed trajectory data with ground truth parameters.
This script runs only during Docker build and is NOT present in the final image."""
import json
import math

# Ground truth physical parameters
m1, m2 = 1.5, 0.8
l1, l2 = 0.75, 0.5
b1, b2 = 0.03, 0.02

# Ground truth initial velocities (unknown to the agent)
qd1_0, qd2_0 = 0.3, -0.2

# Simulation configuration (known to the agent)
g = 9.81
dt = 0.005
n_steps = 300
q1, q2 = 1.2, -0.8
qd1, qd2 = qd1_0, qd2_0

observations = []
for step in range(n_steps + 1):
    # Record positions only (not velocities)
    observations.append([q1, q2])
    if step < n_steps:
        lc1 = l1 / 2.0
        lc2 = l2 / 2.0
        I1 = m1 * l1 * l1 / 12.0
        I2 = m2 * l2 * l2 / 12.0
        cos_q2 = math.cos(q2)
        sin_q2 = math.sin(q2)
        a11 = m1 * lc1**2 + I1 + m2 * (l1**2 + lc2**2 + 2 * l1 * lc2 * cos_q2) + I2
        a12 = m2 * lc2**2 + I2 + m2 * l1 * lc2 * cos_q2
        a22 = m2 * lc2**2 + I2
        h = m2 * l1 * lc2 * sin_q2
        c1 = -h * qd2 * (2 * qd1 + qd2)
        c2 = h * qd1**2
        sin_q1 = math.sin(q1)
        sin_q12 = math.sin(q1 + q2)
        g1 = (m1 * lc1 + m2 * l1) * g * sin_q1 + m2 * lc2 * g * sin_q12
        g2 = m2 * lc2 * g * sin_q12
        rhs1 = -c1 - g1 - b1 * qd1
        rhs2 = -c2 - g2 - b2 * qd2
        det = a11 * a22 - a12 * a12
        qdd1 = (a22 * rhs1 - a12 * rhs2) / det
        qdd2 = (-a12 * rhs1 + a11 * rhs2) / det
        qd1 += dt * qdd1
        qd2 += dt * qdd2
        q1 += dt * qd1
        q2 += dt * qd2

with open('/tmp/trajectory.json', 'w') as f:
    json.dump(observations, f)
print(f"Generated {len(observations)} position observations")
