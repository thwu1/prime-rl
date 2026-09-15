"""Simulation field computation module.

Provides functions to generate 3D scientific simulation data at arbitrary
grid resolutions. These field formulas model a simplified fluid dynamics scenario
with time-varying velocity, decaying temperature, and slowly changing pressure.
"""
import numpy as np

VARIABLE_NAMES = ["velocity_x", "velocity_y", "velocity_z", "temperature", "pressure"]
FULL_SHAPE = (64, 48, 32)
NUM_STEPS = 8
DT = 0.1


def compute_fields(nx, ny, nz, step, dt=0.1):
    """Compute all 5 field variables for the given grid dimensions and timestep.

    Parameters:
        nx, ny, nz: Grid dimensions along each axis
        step: Timestep index (0-based)
        dt: Time increment (default 0.1)

    Returns:
        dict mapping variable name (str) to numpy float64 array of shape (nx, ny, nz)
    """
    t = step * dt
    i = np.arange(nx, dtype=np.float64)
    j = np.arange(ny, dtype=np.float64)
    k = np.arange(nz, dtype=np.float64)
    ii, jj, kk = np.meshgrid(i, j, k, indexing='ij')

    fields = {}
    fields["velocity_x"] = np.sin(2.0 * np.pi * ii / nx) * np.cos(2.0 * np.pi * t)
    fields["velocity_y"] = np.cos(2.0 * np.pi * jj / ny) * np.sin(2.0 * np.pi * t)
    fields["velocity_z"] = 0.5 * np.sin(2.0 * np.pi * kk / nz) * np.cos(np.pi * t)
    fields["temperature"] = (300.0 + 100.0 * np.sin(np.pi * ii / nx)
                             * np.sin(np.pi * jj / ny) * np.exp(-0.5 * t))
    fields["pressure"] = (101325.0 + 5000.0 * np.cos(2.0 * np.pi * kk / nz)
                          * (1.0 - 0.1 * t))

    return fields
