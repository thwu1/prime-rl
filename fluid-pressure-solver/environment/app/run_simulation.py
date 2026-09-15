"""Entry point for running a dam-break fluid simulation."""

import numpy as np
from fluid.grid import MACGrid, FLUID, EMPTY
from fluid.solver import FluidSolver


def setup_dam_break(nx=32, ny=32):
    """Create a dam-break scenario: water column in the left quarter."""
    dx = 1.0 / nx
    grid = MACGrid(nx, ny, dx)
    water_width = nx // 4
    water_height = ny // 2
    for i in range(nx):
        for j in range(ny):
            if i < water_width and j < water_height:
                grid.cell_type[i, j] = FLUID
            else:
                grid.cell_type[i, j] = EMPTY
    return grid


def run_dam_break():
    grid = setup_dam_break(nx=32, ny=32)
    solver = FluidSolver(grid, gravity=(0.0, -9.81))
    dt = 0.002
    for step in range(50):
        iters, residual = solver.step(dt)
        max_div = grid.max_divergence()
        max_u = float(np.max(np.abs(grid.u)))
        max_v = float(np.max(np.abs(grid.v)))
        ke = 0.5 * (np.sum(grid.u[1:-1, :] ** 2)
                     + np.sum(grid.v[:, 1:-1] ** 2))
        print(f"Step {step:3d} | t={solver.time:.4f} | "
              f"PCG iters={iters:3d} residual={residual:.2e} | "
              f"max_div={max_div:.2e} | max_u={max_u:.4f} max_v={max_v:.4f} | "
              f"KE={ke:.6f}")


if __name__ == '__main__':
    run_dam_break()
