"""
Configuration parameters for the double pendulum DAE simulation.

"""

import numpy as np

# --- Physical parameters ---
GRAVITY = np.array([0.0, 0.0, -9.81])

# Link 1
LINK1_LENGTH = 1.0        # meters
LINK1_MASS = 2.0          # kg
LINK1_RADIUS = 0.02       # rod radius for computing I_xx
LINK1_INERTIA = np.diag([0.5 * 2.0 * 0.02**2, 2.0 * 1.0**2 / 12.0, 2.0 * 1.0**2 / 12.0])  # cylindrical rod

# Link 2
LINK2_LENGTH = 0.8        # meters
LINK2_MASS = 1.5          # kg
LINK2_RADIUS = 0.02       # rod radius for computing I_xx
LINK2_INERTIA = np.diag([0.5 * 1.5 * 0.02**2, 1.5 * 0.8**2 / 12.0, 1.5 * 0.8**2 / 12.0])  # cylindrical rod

# Pivot (fixed support) location
PIVOT_POINT = np.array([0.0, 0.0, 0.0])

# --- Integrator parameters ---
TIMESTEP = 0.001          # seconds
T_FINAL = 10.0            # seconds
NEWMARK_BETA = 0.25       # Newmark beta parameter (0.25 = trapezoidal / average acceleration)
NEWMARK_GAMMA = 0.5       # Newmark gamma parameter (0.5 = no numerical damping)

# --- Newton-Raphson parameters ---
NEWTON_MAX_ITER = 50
NEWTON_TOL = 1e-10

# --- Baumgarte stabilization parameters ---
# TODO: These values cause constraint drift and instability.
# Find values that keep constraint violations below 1e-6 over 10 seconds.
BAUMGARTE_ALPHA = 0.0
BAUMGARTE_BETA = 0.0
