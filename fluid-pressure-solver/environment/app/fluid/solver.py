"""Main fluid solver implementing the fractional-step method.

Time integration order:
    1. Advect velocity field (semi-Lagrangian)
    2. Apply external forces (gravity)
    3. Enforce boundary velocities
    4. Pressure projection (enforce incompressibility)
    5. Enforce boundary velocities again
"""

from .advection import advect_velocity
from .forces import apply_gravity
from .pressure import project


class FluidSolver:
    """2D incompressible fluid solver on a MAC grid."""

    def __init__(self, grid, gravity=(0.0, -9.81)):
        self.grid = grid
        self.gravity = gravity
        self.time = 0.0
        self.frame = 0

    def step(self, dt):
        """Advance simulation by one time step. Returns (pcg_iters, residual)."""
        advect_velocity(self.grid, dt)
        apply_gravity(self.grid, dt, self.gravity)
        self.grid.enforce_boundary_velocities()
        iters, residual = project(self.grid, dt)
        self.grid.enforce_boundary_velocities()
        self.time += dt
        self.frame += 1
        return iters, residual
