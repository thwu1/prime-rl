"""Gait trajectory utilities for quadruped locomotion.

Provides functions for computing reference foot trajectories using
cubic Bezier interpolation and phase-based gait pattern definitions.

References:
    Bellegarda & Ijspeert (2022): https://arxiv.org/pdf/2201.00206
    MuJoCo MPC quadruped task implementation
"""

import numpy as np

# Gait phase offsets for common quadruped gaits.
# Foot order: FR (front-right), FL (front-left),
#             RR (rear-right), RL (rear-left).
GAIT_PHASES = {
    'trot': np.array([0, np.pi, np.pi, 0]),
    'walk': np.array([0, 0.5 * np.pi, np.pi, 1.5 * np.pi]),
    'pace': np.array([0, np.pi, 0, np.pi]),
    'bound': np.array([0, 0, np.pi, np.pi]),
    'pronk': np.array([0, 0, 0, 0]),
}


def cubic_bezier_interpolation(y_start, y_end, x):
    """Cubic Bezier interpolation between two values.

    Produces a smooth S-curve transition from y_start to y_end
    as x varies from 0 to 1. The control points are chosen so
    that the curve starts with zero slope at x=0 and ends with
    zero slope at x=1.

    Args:
        y_start: Value at x=0.
        y_end: Value at x=1.
        x: Interpolation parameter in [0, 1].

    Returns:
        Interpolated value along the Bezier curve.
    """
    y_diff = y_end - y_start
    bezier = x**3 + 3 * (x * (1 - x)**2)
    return y_start + y_diff * bezier


def get_rz(phi, swing_height=0.08):
    """Compute reference foot z-height from gait phase angle.

    Maps a phase angle phi in [-pi, pi] to a reference vertical
    position for the foot. In the first half of the gait cycle
    the foot rises (stance-to-swing), in the second half it
    descends back toward the ground (swing-to-stance).

    Args:
        phi: Phase angle in [-pi, pi].
        swing_height: Maximum foot height at the apex of swing.

    Returns:
        Reference foot z-height (>= 0).
    """
    x = (phi + np.pi) / (2 * np.pi)
    stance = cubic_bezier_interpolation(0, swing_height, 2 * x)
    swing = cubic_bezier_interpolation(swing_height, 0, 2 * x - 1)
    return np.where(x <= 0.5, stance, swing)
