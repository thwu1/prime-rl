"""
Cantilever beam simulator based on Dakota test suite (Sandia National Laboratories).

Evaluates a cantilever beam model with area, stress, and displacement responses.
The model accepts design variables (width, thickness) and uncertain parameters
(yield strength, Young's modulus, horizontal/vertical loads).
"""
import math


def cantilever_beam(w, t, R, E, X, Y, L=100.0, D0=2.2535):
    """
    Evaluate cantilever beam responses.

    Parameters
    ----------
    w : float - beam width (design variable)
    t : float - beam thickness (design variable)
    R : float - yield strength (uncertain)
    E : float - Young's modulus (uncertain)
    X : float - horizontal load (uncertain)
    Y : float - vertical load (uncertain)
    L : float - beam length (default 100)
    D0 : float - displacement normalization constant (default 2.2535)

    Returns
    -------
    dict with keys:
        area: cross-sectional area w*t
        stress: combined bending stress from X and Y loads
        displacement: tip displacement normalized by D0
    """
    area = w * t
    stress = 600.0 * Y / (w * t ** 2) + 600.0 * X / (w ** 2 * t)

    D1 = 4.0 * L ** 3 / (E * w * t)
    D2 = (Y / t ** 2) ** 2 + (X / w ** 2) ** 2
    displacement = D1 * math.sqrt(D2) / D0

    return {
        "area": area,
        "stress": stress,
        "displacement": displacement,
    }


if __name__ == "__main__":
    result = cantilever_beam(
        w=2.5, t=3.5, R=40000, E=29e6, X=500, Y=1000
    )
    for key, val in result.items():
        print(f"{key}: {val:.6f}")
