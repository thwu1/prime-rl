"""External force application for the fluid solver."""

from .grid import FLUID


def apply_gravity(grid, dt, gravity=(0.0, -9.81)):
    """Apply gravitational acceleration to velocity faces adjacent to fluid."""
    nx, ny = grid.nx, grid.ny
    gx, gy = gravity

    for i in range(1, nx):
        for j in range(ny):
            if (grid.cell_type[i - 1, j] == FLUID
                    and grid.cell_type[i, j] == FLUID):
                grid.u[i, j] += dt * gx

    for i in range(nx):
        for j in range(1, ny):
            if (grid.cell_type[i, j - 1] == FLUID
                    and grid.cell_type[i, j] == FLUID):
                grid.v[i, j] += dt * gy
