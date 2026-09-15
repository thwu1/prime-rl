"""
Fast Marching Method (FMM) for signed distance field reinitialization.

Given an approximate signed distance field on a 2D grid, the FMM
recomputes distances by solving the Eikonal equation |grad(phi)| = 1
outward from the zero level set.
"""


def reinitialize_sdf(phi, width, height, dx=1.0):
    """
    Reinitialize a 2D signed distance field using FMM.

    The input phi[j][i] is indexed as [row][column] where j is the row
    (y-direction) and i is the column (x-direction). Negative values
    represent the interior and positive values the exterior.

    The output preserves the zero level set location and recomputes
    all distances so that |grad(phi)| ~ 1 everywhere.

    Args:
        phi: list[list[float]], shape [height][width]
        width: int, number of columns
        height: int, number of rows
        dx: float, uniform grid spacing

    Returns:
        list[list[float]], reinitialized SDF with same shape
    """
    raise NotImplementedError("Implement the Fast Marching Method")
