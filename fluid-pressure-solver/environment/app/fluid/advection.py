"""Semi-Lagrangian advection for MAC grid velocity fields.

Uses RK2 (midpoint method) for particle backtracing and bilinear interpolation
for sampling the old velocity at the backtraced position.
"""

import numpy as np
from .grid import FLUID, SOLID


def advect_velocity(grid, dt):
    """Advect the velocity field using the semi-Lagrangian method."""
    nx, ny, dx = grid.nx, grid.ny, grid.dx
    new_u = grid.u.copy()
    new_v = grid.v.copy()

    # Advect u-component (sampled at vertical faces)
    for i in range(1, nx):
        for j in range(ny):
            x = i * dx
            y = (j + 0.5) * dx
            u0, v0 = grid.interpolate_velocity(x, y)
            xm = x - 0.5 * dt * u0
            ym = y - 0.5 * dt * v0
            um, vm = grid.interpolate_velocity(xm, ym)
            xp = max(0.0, min(nx * dx, x - dt * um))
            yp = max(0.0, min(ny * dx, y - dt * vm))
            new_u[i, j] = grid._bilerp(grid.u, xp / dx,
                                        yp / dx - 0.5, nx + 1, ny)

    # Advect v-component (sampled at horizontal faces)
    for i in range(nx):
        for j in range(1, ny):
            x = i * dx
            y = (j + 0.5) * dx
            u0, v0 = grid.interpolate_velocity(x, y)
            xm = x - 0.5 * dt * u0
            ym = y - 0.5 * dt * v0
            um, vm = grid.interpolate_velocity(xm, ym)
            xp = max(0.0, min(nx * dx, x - dt * um))
            yp = max(0.0, min(ny * dx, y - dt * vm))
            new_v[i, j] = grid._bilerp(grid.v, xp / dx - 0.5,
                                        yp / dx, nx, ny + 1)

    grid.u = new_u
    grid.v = new_v
