"""
Kovasznay flow problem specification for the DG Navier-Stokes task.

Provides the exact solution functions, physical parameters, and
discretization settings. The solver must use these definitions and
write results in the specified format to /app/results.json.
"""

import numpy as np

# Domain: unit square [0,1]^2
# Discretization
MESH_N = 16              # cells per side
POLY_DEGREE = 1          # polynomial degree k

# Physics
RE = 25.0                # Reynolds number

# Time stepping (semi-implicit relaxation to steady state)
NUM_STEPS = 25
T_FINAL = 10.0


def velocity_exact(x):
    """Exact velocity field for Kovasznay flow at the given Reynolds number.

    The Kovasznay solution is a steady-state solution to the Navier-Stokes
    equations on a rectangular domain. The parameter lambda is determined
    by the Reynolds number.
    """
    lam = RE / 2 - np.sqrt(RE**2 / 4 + 4 * np.pi**2)
    return np.vstack((
        1 - np.exp(lam * x[0]) * np.cos(2 * np.pi * x[1]),
        (lam / (2 * np.pi)) * np.exp(lam * x[0]) * np.sin(2 * np.pi * x[1]),
    ))


def pressure_exact(x):
    """Exact pressure field for Kovasznay flow at the given Reynolds number."""
    lam = RE / 2 - np.sqrt(RE**2 / 4 + 4 * np.pi**2)
    return 0.5 * (1 - np.exp(2 * lam * x[0]))


def forcing(x):
    """External body force (identically zero for Kovasznay flow)."""
    return np.vstack((np.zeros_like(x[0]), np.zeros_like(x[0])))
