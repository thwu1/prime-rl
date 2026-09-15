"""Panel geometry computation from surface mesh."""
import numpy as np


def compute_panel_geometry(mesh):
    """
    Given mesh of shape (nx, ny, 3), compute panel geometry data.

    Panel corners are defined by four mesh points:
        p1 = mesh[i, j]       (LE, inner)
        p2 = mesh[i+1, j]     (TE, inner)
        p3 = mesh[i, j+1]     (LE, outer)
        p4 = mesh[i+1, j+1]   (TE, outer)

    Returns list of dicts with keys:
        bound_A, bound_B : bound vortex endpoints (quarter-chord)
        collocation      : control point
        normal           : unit outward normal
        dl               : bound vortex segment vector (B - A)
        midpoint         : midpoint of bound vortex
    Panels ordered: spanwise index (j) varies slowest, chordwise (i) fastest.
    """
    nx, ny, _ = mesh.shape
    panels = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            p1 = mesh[i, j]
            p2 = mesh[i + 1, j]
            p3 = mesh[i, j + 1]
            p4 = mesh[i + 1, j + 1]

            # Bound vortex at quarter-chord
            bound_A = 0.75 * p1 + 0.25 * p2  # inner
            bound_B = 0.75 * p3 + 0.25 * p4  # outer

            # Control point location
            coll = 0.5 * 0.5 * (p1 + p3) + 0.5 * 0.5 * (p2 + p4)

            # Normal via diagonals
            d1 = p4 - p1
            d2 = p3 - p2
            n = np.cross(d1, d2)
            n_mag = np.linalg.norm(n)
            if n_mag < 1e-30:
                n = np.array([0.0, 0.0, 1.0])
            else:
                n = n / n_mag

            panels.append({
                "bound_A": bound_A,
                "bound_B": bound_B,
                "collocation": coll,
                "normal": n,
                "dl": bound_B - bound_A,
                "midpoint": 0.5 * (bound_A + bound_B),
            })
    return panels
