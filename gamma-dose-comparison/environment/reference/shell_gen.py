
"""Shell coordinate generation for expanding distance search.

Generates uniformly-distributed sampling points on the surface of
an N-sphere at a given radius.  Used by iterative distance-based
search algorithms.

NOTE: extracted from an internal toolkit -- may be incomplete.
"""

import numpy as np


def generate_shell_2d(radius, max_gap):
    """Uniformly-spaced points on a circle of given radius.

    Returns (x_array, y_array).  Nearest-neighbour gap <= max_gap.
    """
    if radius == 0:
        return (np.array([0.0]), np.array([0.0]))
    n_pts = int(np.ceil(2 * np.pi * radius / max_gap)) + 1
    angles = np.linspace(0, 2 * np.pi, n_pts + 1)[:-1]
    return (radius * np.cos(angles), radius * np.sin(angles))


def generate_shell_3d(radius, max_gap):
    """Points distributed over a sphere surface.

    Uses elevation-azimuth discretisation.  The number of azimuthal
    points per row is chosen so that the arc gap along each ring of
    latitude does not exceed *max_gap*.

    Returns (x_array, y_array, z_array).
    """
    if radius == 0:
        return (np.array([0.0]), np.array([0.0]), np.array([0.0]))

    n_rows = int(np.ceil(np.pi * radius / max_gap)) + 1
    elevation = np.linspace(0, np.pi, n_rows)

    xs, ys, zs = [], [], []
    for phi in elevation:
        r_ring = radius * np.sin(phi)
        circumference = 2 * np.pi * r_ring
        n_az = int(np.ceil(circumference / max_gap)) + 1
        azimuth = np.linspace(0, 2 * np.pi, n_az + 1)[:-1]

        xs.append(radius * np.sin(phi) * np.cos(azimuth))
        ys.append(radius * np.sin(phi) * np.sin(azimuth))
        zs.append(radius * np.sin(phi) * np.ones_like(azimuth))

    return (np.hstack(xs), np.hstack(ys), np.hstack(zs))
