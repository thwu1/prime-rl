
import sys
sys.path.insert(0, '/app')

import pytest
import numpy as np

from fluid.grid import MACGrid, FLUID, SOLID, EMPTY
from fluid.pressure import build_pressure_system, pcg_solve, project
from fluid.solver import FluidSolver


# ---------------------------------------------------------------------------
# Pressure system construction
# ---------------------------------------------------------------------------

class TestPressureSystem:

    def test_uniform_fluid_interior_diagonal(self):
        """Interior cell in an all-fluid grid: 4 non-wall neighbors."""
        grid = MACGrid(4, 4, 0.25)
        grid.cell_type[:, :] = FLUID
        Adiag, _, _, _ = build_pressure_system(grid, 0.01)
        assert Adiag[1, 1] == 4
        assert Adiag[2, 2] == 4

    def test_uniform_fluid_corner_diagonal(self):
        """Corner cell in an all-fluid grid: 2 non-wall neighbors."""
        grid = MACGrid(4, 4, 0.25)
        grid.cell_type[:, :] = FLUID
        Adiag, _, _, _ = build_pressure_system(grid, 0.01)
        assert Adiag[0, 0] == 2

    def test_uniform_fluid_edge_diagonal(self):
        """Edge cell in an all-fluid grid: 3 non-wall neighbors."""
        grid = MACGrid(4, 4, 0.25)
        grid.cell_type[:, :] = FLUID
        Adiag, _, _, _ = build_pressure_system(grid, 0.01)
        assert Adiag[1, 0] == 3

    def test_air_neighbor_contributes_to_diagonal(self):
        """EMPTY (air) neighbor must increase the diagonal coefficient."""
        grid = MACGrid(4, 4, 0.25)
        grid.cell_type[0, 0] = FLUID
        grid.cell_type[1, 0] = FLUID
        grid.cell_type[0, 1] = EMPTY
        Adiag, Ax, Ay, _ = build_pressure_system(grid, 0.01)
        # Cell (0,0): right=FLUID, left=wall, up=EMPTY, down=wall
        # Diagonal must count FLUID + EMPTY = 2
        assert Adiag[0, 0] == 2
        # Off-diagonal coupling to EMPTY must be 0
        assert Ay[0, 0] == 0
        # Off-diagonal coupling to FLUID must be 1
        assert Ax[0, 0] == 1

    def test_solid_excluded_from_system(self):
        """SOLID neighbor contributes to neither diagonal nor coupling."""
        grid = MACGrid(4, 4, 0.25)
        grid.cell_type[:, :] = FLUID
        grid.cell_type[2, 1] = SOLID
        Adiag, _, _, _ = build_pressure_system(grid, 0.01)
        assert Adiag[1, 1] == 3

    def test_single_fluid_cell_surrounded_by_air(self):
        """Single fluid cell with all EMPTY neighbors: diagonal = 4."""
        grid = MACGrid(6, 6, 1.0 / 6)
        grid.cell_type[3, 3] = FLUID
        # All 4 neighbors are EMPTY (not wall)
        Adiag, Ax, Ay, _ = build_pressure_system(grid, 0.01)
        assert Adiag[3, 3] == 4

    def test_rhs_zero_for_zero_velocity(self):
        """Zero velocity must produce zero RHS."""
        grid = MACGrid(4, 4, 0.25)
        grid.cell_type[:, :] = FLUID
        _, _, _, rhs = build_pressure_system(grid, 0.01)
        assert np.allclose(rhs, 0.0)

    def test_rhs_nonzero_for_divergent_velocity(self):
        """Non-zero velocity divergence must produce non-zero RHS."""
        grid = MACGrid(4, 4, 0.25)
        grid.cell_type[:, :] = FLUID
        grid.u[2, 1] = 1.0
        _, _, _, rhs = build_pressure_system(grid, 0.01)
        assert rhs[1, 1] != 0.0


# ---------------------------------------------------------------------------
# PCG solver
# ---------------------------------------------------------------------------

class TestPCGSolver:

    def test_zero_rhs(self):
        grid = MACGrid(8, 8, 0.125)
        grid.cell_type[:, :] = FLUID
        Adiag, Ax, Ay, rhs = build_pressure_system(grid, 0.01)
        pressure, iters, residual = pcg_solve(
            Adiag, Ax, Ay, rhs, grid.cell_type)
        assert np.allclose(pressure, 0.0, atol=1e-10)

    def test_convergence_with_air_boundary(self):
        """PCG must converge when Dirichlet BC comes from air cells."""
        grid = MACGrid(16, 16, 1.0 / 16)
        grid.cell_type[:, :] = FLUID
        grid.cell_type[:, -1] = EMPTY
        for i in range(grid.nx + 1):
            for j in range(grid.ny):
                grid.u[i, j] = 0.1 * np.sin(2 * np.pi * i / grid.nx)
        grid.enforce_boundary_velocities()
        Adiag, Ax, Ay, rhs = build_pressure_system(grid, 0.01)
        pressure, iters, residual = pcg_solve(
            Adiag, Ax, Ay, rhs, grid.cell_type)
        assert residual < 1e-6, f"PCG residual={residual}"
        assert iters < 200, f"PCG iters={iters}"


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

class TestProjection:

    def test_divergence_free_after_projection(self):
        """Random divergent field must become divergence-free."""
        grid = MACGrid(16, 16, 1.0 / 16)
        grid.cell_type[:, :] = FLUID
        grid.cell_type[:, -1] = EMPTY
        rng = np.random.RandomState(42)
        grid.u = rng.randn(17, 16) * 0.1
        grid.v = rng.randn(16, 17) * 0.1
        grid.enforce_boundary_velocities()
        project(grid, 0.01)
        grid.enforce_boundary_velocities()
        max_div = grid.max_divergence()
        assert max_div < 1e-5, f"max divergence = {max_div}"

    def test_preserves_divergence_free_field(self):
        """Projection should not significantly alter a div-free field."""
        n = 16
        dx = 1.0 / n
        grid = MACGrid(n, n, dx)
        grid.cell_type[:, :] = FLUID
        for i in range(n + 1):
            for j in range(n):
                x = i * dx
                y = (j + 0.5) * dx
                grid.u[i, j] = np.sin(np.pi * x) * np.pi * np.cos(np.pi * y)
        for i in range(n):
            for j in range(n + 1):
                x = (i + 0.5) * dx
                y = j * dx
                grid.v[i, j] = -np.pi * np.cos(np.pi * x) * np.sin(np.pi * y)
        grid.enforce_boundary_velocities()
        u_before = grid.u.copy()
        v_before = grid.v.copy()
        project(grid, 0.01)
        grid.enforce_boundary_velocities()
        assert np.max(np.abs(grid.u - u_before)) < 0.1
        assert np.max(np.abs(grid.v - v_before)) < 0.1

    def test_hydrostatic_equilibrium(self):
        """Fluid column under gravity: projection should cancel gravity."""
        n = 16
        dx = 1.0 / n
        grid = MACGrid(n, n, dx)
        for i in range(n):
            for j in range(n // 2):
                grid.cell_type[i, j] = FLUID
        dt = 0.005
        from fluid.forces import apply_gravity
        apply_gravity(grid, dt, gravity=(0.0, -9.81))
        grid.enforce_boundary_velocities()
        project(grid, dt)
        grid.enforce_boundary_velocities()
        max_div = grid.max_divergence()
        assert max_div < 1e-5, f"divergence = {max_div}"
        assert np.max(np.abs(grid.u)) < 1e-6, "spurious horizontal velocity"

    def test_single_fluid_cell(self):
        """Lone fluid cell surrounded by air must project correctly."""
        grid = MACGrid(4, 4, 0.25)
        grid.cell_type[2, 2] = FLUID
        grid.v[2, 3] = -0.05
        grid.enforce_boundary_velocities()
        project(grid, 0.01)
        grid.enforce_boundary_velocities()
        max_div = grid.max_divergence()
        assert max_div < 1e-5, f"divergence = {max_div}"

    def test_mixed_boundaries(self):
        """Projection with mixed fluid / air / solid cells."""
        grid = MACGrid(8, 8, 0.125)
        grid.cell_type[2:6, 1:4] = FLUID
        grid.cell_type[3, 2] = SOLID
        dt = 0.01
        from fluid.forces import apply_gravity
        apply_gravity(grid, dt)
        grid.enforce_boundary_velocities()
        project(grid, dt)
        grid.enforce_boundary_velocities()
        max_div = grid.max_divergence()
        assert max_div < 1e-5, f"divergence = {max_div}"


# ---------------------------------------------------------------------------
# Gravity application
# ---------------------------------------------------------------------------

class TestGravity:

    def test_gravity_reaches_free_surface(self):
        """Gravity must be applied to v-faces at the fluid-air interface."""
        grid = MACGrid(4, 4, 0.25)
        for i in range(4):
            for j in range(2):
                grid.cell_type[i, j] = FLUID
        dt = 0.01
        from fluid.forces import apply_gravity
        apply_gravity(grid, dt, gravity=(0.0, -9.81))
        # v-face at (*, 2) is between FLUID row 1 and EMPTY row 2
        for i in range(4):
            assert grid.v[i, 2] < 0, \
                f"v[{i},2]={grid.v[i, 2]}: gravity missing at free surface"

    def test_gravity_not_applied_in_pure_air(self):
        """Gravity should not be applied to faces between two air cells."""
        grid = MACGrid(4, 4, 0.25)
        grid.cell_type[0, 0] = FLUID
        dt = 0.01
        from fluid.forces import apply_gravity
        apply_gravity(grid, dt, gravity=(0.0, -9.81))
        # v-face at (2, 2) is between EMPTY(2,1) and EMPTY(2,2)
        assert grid.v[2, 2] == 0.0, "gravity applied in pure air region"


# ---------------------------------------------------------------------------
# Advection
# ---------------------------------------------------------------------------

class TestAdvection:

    def test_v_advection_face_positions(self):
        """V-component advection must sample from correct face positions."""
        n = 16
        dx = 1.0 / n
        grid = MACGrid(n, n, dx)
        grid.cell_type[:, :] = FLUID
        # Spatially varying v-field
        for i in range(n):
            for j in range(n + 1):
                x = (i + 0.5) * dx
                y = j * dx
                grid.v[i, j] = np.sin(np.pi * x) * np.cos(np.pi * y)
        grid.u[:, :] = 0.0
        grid.enforce_boundary_velocities()
        v_before = grid.v.copy()
        from fluid.advection import advect_velocity
        advect_velocity(grid, 0.001)
        # With u=0 and tiny dt, interior v should barely change
        max_change = np.max(np.abs(
            grid.v[2:-2, 2:-2] - v_before[2:-2, 2:-2]))
        assert max_change < 0.05, \
            f"v changed by {max_change}: check advection face positions"


# ---------------------------------------------------------------------------
# Full dam-break simulation
# ---------------------------------------------------------------------------

class TestDamBreak:

    @staticmethod
    def _make_dam():
        from run_simulation import setup_dam_break
        return setup_dam_break(nx=16, ny=16)

    def test_simulation_completes(self):
        """Dam-break simulation must complete without solver failure."""
        grid = self._make_dam()
        solver = FluidSolver(grid, gravity=(0.0, -9.81))
        for _ in range(10):
            iters, residual = solver.step(0.002)
            assert residual < 1e-4, f"solver failed: residual={residual}"

    def test_divergence_bounded(self):
        """Divergence must stay small across all time steps."""
        grid = self._make_dam()
        solver = FluidSolver(grid, gravity=(0.0, -9.81))
        for step in range(10):
            solver.step(0.002)
            max_div = grid.max_divergence()
            assert max_div < 1e-4, f"step {step}: max_div={max_div}"

    def test_velocity_bounded(self):
        """Velocities must remain physically plausible."""
        grid = self._make_dam()
        solver = FluidSolver(grid, gravity=(0.0, -9.81))
        for step in range(10):
            solver.step(0.002)
            max_speed = np.sqrt(np.max(grid.u ** 2) + np.max(grid.v ** 2))
            assert max_speed < 10.0, f"step {step}: speed={max_speed}"

    def test_energy_increases_under_gravity(self):
        """KE must increase as gravity converts potential energy."""
        grid = self._make_dam()
        solver = FluidSolver(grid, gravity=(0.0, -9.81))
        energies = []
        for _ in range(10):
            solver.step(0.002)
            ke = 0.5 * (np.sum(grid.u[1:-1, :] ** 2)
                        + np.sum(grid.v[:, 1:-1] ** 2))
            energies.append(ke)
        assert energies[-1] > energies[0], "KE should grow under gravity"
        assert all(0 < e < 1e6 for e in energies), "unphysical energy"
