"""MAC (Marker-And-Cell) staggered grid for 2D incompressible fluid simulation.

Grid Layout:
    Pressure stored at cell centers: p[i,j] at ((i+0.5)*dx, (j+0.5)*dx)
    U-velocity at vertical faces:    u[i,j] at (i*dx, (j+0.5)*dx)
    V-velocity at horizontal faces:  v[i,j] at ((i+0.5)*dx, j*dx)

Cell types:
    FLUID (0): Contains fluid, pressure unknown
    SOLID (1): Solid obstacle, no-penetration BC
    EMPTY (2): Air/vacuum, pressure = 0 (atmospheric)

Array shapes:
    pressure, cell_type: (nx, ny)
    u: (nx+1, ny)   — one more column of faces than cells
    v: (nx, ny+1)   — one more row of faces than cells
"""

import numpy as np

FLUID = 0
SOLID = 1
EMPTY = 2


class MACGrid:
    """2D staggered grid for incompressible fluid simulation."""

    def __init__(self, nx, ny, dx):
        self.nx = nx
        self.ny = ny
        self.dx = dx
        self.pressure = np.zeros((nx, ny), dtype=np.float64)
        self.u = np.zeros((nx + 1, ny), dtype=np.float64)
        self.v = np.zeros((nx, ny + 1), dtype=np.float64)
        self.cell_type = np.full((nx, ny), EMPTY, dtype=np.int32)

    def divergence(self, i, j):
        """Discrete velocity divergence at cell (i,j)."""
        return (self.u[i + 1, j] - self.u[i, j]
                + self.v[i, j + 1] - self.v[i, j]) / self.dx

    def max_divergence(self):
        """Maximum absolute divergence over all fluid cells."""
        max_div = 0.0
        for i in range(self.nx):
            for j in range(self.ny):
                if self.cell_type[i, j] == FLUID:
                    max_div = max(max_div, abs(self.divergence(i, j)))
        return max_div

    def enforce_boundary_velocities(self):
        """Zero normal velocity at solid cell faces and domain walls."""
        for i in range(self.nx):
            for j in range(self.ny):
                if self.cell_type[i, j] == SOLID:
                    self.u[i, j] = 0.0
                    self.u[i + 1, j] = 0.0
                    self.v[i, j] = 0.0
                    self.v[i, j + 1] = 0.0
        # Domain boundary walls
        self.u[0, :] = 0.0
        self.u[self.nx, :] = 0.0
        self.v[:, 0] = 0.0
        self.v[:, self.ny] = 0.0

    def interpolate_velocity(self, x, y):
        """Bilinearly interpolate velocity at world position (x, y)."""
        u_val = self._bilerp(self.u, x / self.dx,
                             y / self.dx - 0.5, self.nx + 1, self.ny)
        v_val = self._bilerp(self.v, x / self.dx - 0.5,
                             y / self.dx, self.nx, self.ny + 1)
        return u_val, v_val

    @staticmethod
    def _bilerp(field, gx, gy, sx, sy):
        """Bilinear interpolation with clamped indices."""
        i = int(np.floor(gx))
        j = int(np.floor(gy))
        fx = gx - i
        fy = gy - j
        i = max(0, min(i, sx - 2))
        j = max(0, min(j, sy - 2))
        fx = max(0.0, min(1.0, fx))
        fy = max(0.0, min(1.0, fy))
        return ((1 - fx) * (1 - fy) * field[i, j]
                + fx * (1 - fy) * field[i + 1, j]
                + (1 - fx) * fy * field[i, j + 1]
                + fx * fy * field[i + 1, j + 1])

    def copy(self):
        """Deep copy of this grid."""
        g = MACGrid(self.nx, self.ny, self.dx)
        g.pressure = self.pressure.copy()
        g.u = self.u.copy()
        g.v = self.v.copy()
        g.cell_type = self.cell_type.copy()
        return g
