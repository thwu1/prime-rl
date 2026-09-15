"""Pressure projection for enforcing incompressibility on a 2D MAC grid.

Complete implementation of the pressure solve: Laplacian construction,
MIC(0) preconditioner, PCG solver, and velocity correction.
"""

import math
import numpy as np
from .grid import MACGrid, FLUID, SOLID, EMPTY


def build_pressure_system(grid, dt):
    """Build the pressure Laplacian matrix and RHS vector."""
    nx, ny, dx = grid.nx, grid.ny, grid.dx
    Adiag = np.zeros((nx, ny), dtype=np.float64)
    Ax = np.zeros((nx, ny), dtype=np.float64)
    Ay = np.zeros((nx, ny), dtype=np.float64)
    rhs = np.zeros((nx, ny), dtype=np.float64)

    for i in range(nx):
        for j in range(ny):
            if grid.cell_type[i, j] != FLUID:
                continue

            # Right neighbor (i+1, j)
            if i + 1 < nx:
                if grid.cell_type[i + 1, j] == FLUID:
                    Adiag[i, j] += 1
                    Ax[i, j] = 1
                elif grid.cell_type[i + 1, j] == EMPTY:
                    Adiag[i, j] += 1

            # Left neighbor (i-1, j)
            if i - 1 >= 0:
                if grid.cell_type[i - 1, j] == FLUID:
                    Adiag[i, j] += 1
                elif grid.cell_type[i - 1, j] == EMPTY:
                    Adiag[i, j] += 1

            # Top neighbor (i, j+1)
            if j + 1 < ny:
                if grid.cell_type[i, j + 1] == FLUID:
                    Adiag[i, j] += 1
                    Ay[i, j] = 1
                elif grid.cell_type[i, j + 1] == EMPTY:
                    Adiag[i, j] += 1

            # Bottom neighbor (i, j-1)
            if j - 1 >= 0:
                if grid.cell_type[i, j - 1] == FLUID:
                    Adiag[i, j] += 1
                elif grid.cell_type[i, j - 1] == EMPTY:
                    Adiag[i, j] += 1

            # RHS = -(dx/dt) * raw velocity differences
            vel_sum = (grid.u[i + 1, j] - grid.u[i, j]
                       + grid.v[i, j + 1] - grid.v[i, j])
            rhs[i, j] = -(dx / dt) * vel_sum

    return Adiag, Ax, Ay, rhs


def build_preconditioner(Adiag, Ax, Ay, cell_type):
    """Compute MIC(0) preconditioner values."""
    nx, ny = Adiag.shape
    precon = np.zeros((nx, ny), dtype=np.float64)
    tau = 0.97
    sigma = 0.25

    for i in range(nx):
        for j in range(ny):
            if cell_type[i, j] != FLUID:
                continue

            e = Adiag[i, j]

            if i > 0 and cell_type[i - 1, j] == FLUID:
                px = Ax[i - 1, j] * precon[i - 1, j]
                e -= px * px
                e -= tau * (Ax[i - 1, j] * Ay[i - 1, j]
                            * precon[i - 1, j] ** 2)

            if j > 0 and cell_type[i, j - 1] == FLUID:
                py = Ay[i, j - 1] * precon[i, j - 1]
                e -= py * py
                e -= tau * (Ay[i, j - 1] * Ax[i, j - 1]
                            * precon[i, j - 1] ** 2)

            if e < sigma * Adiag[i, j]:
                e = Adiag[i, j]

            if e > 0:
                precon[i, j] = 1.0 / math.sqrt(e)

    return precon


def apply_preconditioner(r, Adiag, Ax, Ay, precon, cell_type):
    """Apply MIC(0) preconditioner: solve M z = r."""
    nx, ny = Adiag.shape
    q = np.zeros((nx, ny), dtype=np.float64)
    z = np.zeros((nx, ny), dtype=np.float64)

    # Forward substitution: L q = r
    # L has negative off-diagonals for the pos-def Laplacian, so
    # q_i = precon_i * (r_i - L_{i,left}*q_left - L_{i,below}*q_below)
    #      = precon_i * (r_i + Ax*precon_left*q_left + Ay*precon_below*q_below)
    for i in range(nx):
        for j in range(ny):
            if cell_type[i, j] != FLUID:
                continue
            t = r[i, j]
            if i > 0 and cell_type[i - 1, j] == FLUID:
                t += Ax[i - 1, j] * precon[i - 1, j] * q[i - 1, j]
            if j > 0 and cell_type[i, j - 1] == FLUID:
                t += Ay[i, j - 1] * precon[i, j - 1] * q[i, j - 1]
            q[i, j] = t * precon[i, j]

    # Backward substitution: L^T z = q
    for i in range(nx - 1, -1, -1):
        for j in range(ny - 1, -1, -1):
            if cell_type[i, j] != FLUID:
                continue
            t = q[i, j]
            if i + 1 < nx and cell_type[i + 1, j] == FLUID:
                t += Ax[i, j] * precon[i, j] * z[i + 1, j]
            if j + 1 < ny and cell_type[i, j + 1] == FLUID:
                t += Ay[i, j] * precon[i, j] * z[i, j + 1]
            z[i, j] = t * precon[i, j]

    return z


def _apply_A(Adiag, Ax, Ay, x, cell_type):
    """Sparse matrix-vector product A*x."""
    nx, ny = Adiag.shape
    result = np.zeros((nx, ny), dtype=np.float64)
    for i in range(nx):
        for j in range(ny):
            if cell_type[i, j] != FLUID:
                continue
            val = Adiag[i, j] * x[i, j]
            if i + 1 < nx and cell_type[i + 1, j] == FLUID:
                val -= Ax[i, j] * x[i + 1, j]
            if i > 0 and cell_type[i - 1, j] == FLUID:
                val -= Ax[i - 1, j] * x[i - 1, j]
            if j + 1 < ny and cell_type[i, j + 1] == FLUID:
                val -= Ay[i, j] * x[i, j + 1]
            if j > 0 and cell_type[i, j - 1] == FLUID:
                val -= Ay[i, j - 1] * x[i, j - 1]
            result[i, j] = val
    return result


def _dot(a, b, cell_type):
    """Dot product over fluid cells."""
    s = 0.0
    nx, ny = a.shape
    for i in range(nx):
        for j in range(ny):
            if cell_type[i, j] == FLUID:
                s += a[i, j] * b[i, j]
    return s


def _max_abs(a, cell_type):
    """Max absolute value over fluid cells."""
    m = 0.0
    nx, ny = a.shape
    for i in range(nx):
        for j in range(ny):
            if cell_type[i, j] == FLUID:
                m = max(m, abs(a[i, j]))
    return m


def pcg_solve(Adiag, Ax, Ay, rhs, cell_type, tol=1e-6, max_iter=200):
    """Solve A p = rhs via Preconditioned Conjugate Gradient."""
    nx, ny = Adiag.shape

    if _max_abs(rhs, cell_type) < 1e-15:
        return np.zeros((nx, ny), dtype=np.float64), 0, 0.0

    pressure = np.zeros((nx, ny), dtype=np.float64)
    precon = build_preconditioner(Adiag, Ax, Ay, cell_type)

    r = rhs.copy()
    z = apply_preconditioner(r, Adiag, Ax, Ay, precon, cell_type)
    s = z.copy()
    sigma = _dot(z, r, cell_type)

    for iteration in range(1, max_iter + 1):
        z = _apply_A(Adiag, Ax, Ay, s, cell_type)
        denom = _dot(z, s, cell_type)
        if abs(denom) < 1e-30:
            break
        alpha = sigma / denom

        for i in range(nx):
            for j in range(ny):
                if cell_type[i, j] == FLUID:
                    pressure[i, j] += alpha * s[i, j]
                    r[i, j] -= alpha * z[i, j]

        max_r = _max_abs(r, cell_type)
        if max_r < tol:
            return pressure, iteration, max_r

        z = apply_preconditioner(r, Adiag, Ax, Ay, precon, cell_type)
        sigma_new = _dot(z, r, cell_type)
        if abs(sigma) < 1e-30:
            break
        beta = sigma_new / sigma

        for i in range(nx):
            for j in range(ny):
                if cell_type[i, j] == FLUID:
                    s[i, j] = z[i, j] + beta * s[i, j]

        sigma = sigma_new

    return pressure, max_iter, _max_abs(r, cell_type)


def project(grid, dt):
    """Pressure projection: build system, solve, correct velocities."""
    Adiag, Ax, Ay, rhs = build_pressure_system(grid, dt)
    pressure, iterations, residual = pcg_solve(
        Adiag, Ax, Ay, rhs, grid.cell_type)

    nx, ny, dx = grid.nx, grid.ny, grid.dx
    scale = dt / dx

    # Correct u-velocity at internal vertical faces
    for i in range(1, nx):
        for j in range(ny):
            if grid.cell_type[i - 1, j] == SOLID or grid.cell_type[i, j] == SOLID:
                continue
            p_left = (pressure[i - 1, j]
                      if grid.cell_type[i - 1, j] == FLUID else 0.0)
            p_right = (pressure[i, j]
                       if grid.cell_type[i, j] == FLUID else 0.0)
            grid.u[i, j] -= scale * (p_right - p_left)

    # Correct v-velocity at internal horizontal faces
    for i in range(nx):
        for j in range(1, ny):
            if grid.cell_type[i, j - 1] == SOLID or grid.cell_type[i, j] == SOLID:
                continue
            p_bottom = (pressure[i, j - 1]
                        if grid.cell_type[i, j - 1] == FLUID else 0.0)
            p_top = (pressure[i, j]
                     if grid.cell_type[i, j] == FLUID else 0.0)
            grid.v[i, j] -= scale * (p_top - p_bottom)

    grid.pressure = pressure
    return iterations, residual
