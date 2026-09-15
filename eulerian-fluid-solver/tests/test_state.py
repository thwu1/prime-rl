
import sys
import math
import os
sys.path.insert(0, '/app')
import pytest
from fluid import EulerianFluid


class TestBuildAndLoad:
    def test_shared_library_exists(self):
        """A compiled shared library exists in /app."""
        so_files = [f for f in os.listdir('/app') if f.endswith('.so')]
        assert len(so_files) > 0, \
            "No .so file found in /app/ — Makefile may not be fixed"

    def test_module_imports(self):
        """The fluid module imports and the C library loads via ctypes."""
        f = EulerianFluid(1000.0, 5, 5, 0.2)
        assert f is not None


class TestModuleStructure:
    def test_instantiate_and_fields(self):
        """Module exists and class can be instantiated with correct fields."""
        f = EulerianFluid(1000.0, 10, 10, 0.1)
        assert f is not None
        assert hasattr(f, 'u')
        assert hasattr(f, 'v')
        assert hasattr(f, 'p')
        assert hasattr(f, 's')
        assert hasattr(f, 'm')

    def test_grid_dimensions(self):
        """Grid dimensions include 2 extra boundary cells per axis."""
        f = EulerianFluid(1000.0, 50, 50, 0.02)
        assert f.numX == 52
        assert f.numY == 52
        assert len(f.u) == 52 * 52
        assert len(f.v) == 52 * 52
        assert len(f.p) == 52 * 52
        assert len(f.s) == 52 * 52
        assert len(f.m) == 52 * 52


class TestSetup:
    def test_wind_tunnel_boundaries(self):
        """Wind tunnel has correct wall and inlet configuration."""
        f = EulerianFluid(1000.0, 50, 50, 0.02)
        f.setup_wind_tunnel(2.0)
        n = f.numY
        # Left wall solid
        for j in range(n):
            assert f.s[0 * n + j] == 0.0
        # Bottom wall solid
        for i in range(f.numX):
            assert f.s[i * n + 0] == 0.0
        # Top wall solid
        for i in range(f.numX):
            assert f.s[i * n + (n - 1)] == 0.0
        # Interior cells must be fluid
        for i in range(1, f.numX):
            for j in range(1, n - 1):
                assert f.s[i * n + j] == 1.0, f"Cell ({i},{j}) should be fluid"
        # Inlet velocity
        for j in range(n):
            assert abs(f.u[1 * n + j] - 2.0) < 1e-10

    def test_obstacle_solid_cells(self):
        """Cells inside the obstacle circle are marked solid."""
        f = EulerianFluid(1000.0, 50, 50, 0.02)
        f.setup_wind_tunnel(2.0)
        cx, cy, r = 0.4, 0.5, 0.1
        f.set_obstacle(cx, cy, r)
        n = f.numY
        h = f.h
        obstacle_count = 0
        for i in range(1, f.numX - 1):
            for j in range(1, n - 1):
                dx = (i + 0.5) * h - cx
                dy = (j + 0.5) * h - cy
                if dx * dx + dy * dy < r * r:
                    assert f.s[i * n + j] == 0.0, \
                        f"Obstacle cell ({i},{j}) should be solid"
                    obstacle_count += 1
        assert obstacle_count > 10, \
            f"Expected >10 obstacle cells, found {obstacle_count}"


class TestBoundaryPhysics:
    def test_gravity_respects_solid_boundaries(self):
        """Gravity must not act at faces adjacent to solid cells."""
        f = EulerianFluid(1000.0, 10, 10, 0.1)
        n = f.numY
        # Tank setup: walls on all sides
        for i in range(f.numX):
            for j in range(n):
                if i == 0 or i == f.numX - 1 or j == 0 or j == n - 1:
                    f.s[i * n + j] = 0.0
                else:
                    f.s[i * n + j] = 1.0
        dt = 1.0 / 60.0
        f.integrate(dt, -9.81)
        # Cell (5,5) with fluid below at (5,4): v should be gravity*dt
        assert abs(f.v[5 * n + 5] - (-9.81 * dt)) < 1e-10, \
            f"v[5,5] should be {-9.81 * dt}"
        # Cell face at j=1 with solid below (j=0): v should NOT be modified
        assert abs(f.v[5 * n + 1]) < 1e-10, \
            "v at face between solid and fluid should not get gravity"

    def test_obstacle_velocity_zero(self):
        """Velocity inside a deeply interior obstacle cell remains near zero."""
        f = EulerianFluid(1000.0, 50, 50, 0.02)
        f.setup_wind_tunnel(2.0)
        cx, cy, r = 0.4, 0.5, 0.1
        f.set_obstacle(cx, cy, r)
        dt = 1.0 / 60.0
        for _ in range(10):
            f.simulate(dt, 0.0, 40, 1.9)
        n = f.numY
        h = f.h
        for i in range(2, f.numX - 2):
            for j in range(2, n - 2):
                dx = (i + 0.5) * h - cx
                dy = (j + 0.5) * h - cy
                if dx * dx + dy * dy < (r * 0.5) ** 2:
                    assert abs(f.u[i * n + j]) < 0.01, \
                        f"u inside obstacle at ({i},{j}) = {f.u[i * n + j]}"


class TestIncompressibility:
    def test_closed_tank_divergence(self):
        """Pressure solver reduces divergence to near zero in a closed tank."""
        f = EulerianFluid(1000.0, 20, 20, 0.05)
        n = f.numY
        # Closed tank: walls on all sides
        for i in range(f.numX):
            for j in range(n):
                if i == 0 or i == f.numX - 1 or j == 0 or j == n - 1:
                    f.s[i * n + j] = 0.0
                else:
                    f.s[i * n + j] = 1.0
        # Create divergent velocity perturbation
        ci, cj = f.numX // 2, n // 2
        f.u[ci * n + cj] = 5.0
        f.u[(ci + 1) * n + cj] = -3.0
        f.v[ci * n + cj] = 2.0
        div_before = f.max_divergence()
        assert div_before > 1.0, f"Initial divergence should be large, got {div_before}"
        f.solve_incompressibility(100, 1.0 / 60, 1.5)
        div_after = f.max_divergence()
        assert div_after < 0.01, \
            f"After 100 iterations, tank divergence should be < 0.01, got {div_after}"

    def test_overrelaxation_accelerates_convergence(self):
        """Over-relaxation with omega>1 converges faster than omega=1."""
        def make_tank():
            f = EulerianFluid(1000.0, 20, 20, 0.05)
            n = f.numY
            for i in range(f.numX):
                for j in range(n):
                    if i == 0 or i == f.numX - 1 or j == 0 or j == n - 1:
                        f.s[i * n + j] = 0.0
                    else:
                        f.s[i * n + j] = 1.0
            ci, cj = f.numX // 2, n // 2
            f.u[ci * n + cj] = 5.0
            f.u[(ci + 1) * n + cj] = -3.0
            f.v[ci * n + cj] = 2.0
            return f

        f1 = make_tank()
        f1.solve_incompressibility(100, 1.0 / 60, 1.0)
        div_no_sor = f1.max_divergence()

        f2 = make_tank()
        f2.solve_incompressibility(100, 1.0 / 60, 1.5)
        div_with_sor = f2.max_divergence()

        assert div_with_sor < div_no_sor, \
            f"Over-relaxation should converge faster: w=1.0->{div_no_sor:.8f}, w=1.5->{div_with_sor:.8f}"

    def test_wind_tunnel_divergence_reduction(self):
        """Additional solver iterations further reduce divergence in developed flow."""
        f = EulerianFluid(1000.0, 50, 50, 0.02)
        f.setup_wind_tunnel(2.0)
        f.set_obstacle(0.4, 0.5, 0.1)
        dt = 1.0 / 60.0
        for _ in range(5):
            f.simulate(dt, 0.0, 40, 1.9)
        div_before = f.max_divergence()
        f.integrate(dt, 0.0)
        for k in range(len(f.p)):
            f.p[k] = 0.0
        f.solve_incompressibility(100, dt, 1.9)
        div_after = f.max_divergence()
        assert div_after < div_before * 0.5, \
            f"Extra solver pass should reduce divergence: {div_before:.4f} -> {div_after:.4f}"
        assert div_after < 0.2, \
            f"After projection, divergence should be < 0.2, got {div_after}"


class TestFieldInterpolation:
    def test_smoke_at_cell_center(self):
        """Scalar field interpolation at a cell center returns exact cell value."""
        f = EulerianFluid(1000.0, 10, 10, 0.1)
        n = f.numY
        h = f.h
        for i in range(f.numX):
            for j in range(n):
                f.m[i * n + j] = i * 0.1 + j * 0.01
        val = f.sample_field(5.5 * h, 5.5 * h, 'smoke')
        assert abs(val - 0.55) < 0.01, f"Expected ~0.55, got {val}"

    def test_smoke_interpolated(self):
        """Scalar field interpolation between cells produces correct blend."""
        f = EulerianFluid(1000.0, 10, 10, 0.1)
        n = f.numY
        h = f.h
        for i in range(f.numX):
            for j in range(n):
                f.m[i * n + j] = i * 0.1 + j * 0.01
        val = f.sample_field(6.0 * h, 5.5 * h, 'smoke')
        expected = 0.5 * 0.55 + 0.5 * 0.65
        assert abs(val - expected) < 0.01, f"Expected ~{expected}, got {val}"

    def test_v_field_at_face_position(self):
        """V-velocity sampled at the exact grid face position returns the stored value."""
        f = EulerianFluid(1000.0, 10, 10, 0.1)
        n = f.numY
        h = f.h
        for i in range(f.numX):
            for j in range(n):
                f.v[i * n + j] = float(j)
        # v[5,5] sits at face position (5*h+h/2, 5*h) on the staggered grid
        val = f.sample_field(5 * h + 0.5 * h, 5 * h, 'v')
        assert abs(val - 5.0) < 0.1, f"v-field at face should be 5.0, got {val}"

    def test_u_field_at_face_position(self):
        """U-velocity sampled at the exact grid face position returns the stored value."""
        f = EulerianFluid(1000.0, 10, 10, 0.1)
        n = f.numY
        h = f.h
        for i in range(f.numX):
            for j in range(n):
                f.u[i * n + j] = float(i)
        # u[5,5] sits at face position (5*h, 5*h+h/2)
        val = f.sample_field(5 * h, 5 * h + 0.5 * h, 'u')
        assert abs(val - 5.0) < 0.1, f"u-field at face should be 5.0, got {val}"


class TestFullSimulation:
    def test_simulation_stability(self):
        """Simulation runs 30 steps without NaN or unbounded values."""
        f = EulerianFluid(1000.0, 50, 50, 0.02)
        f.setup_wind_tunnel(2.0)
        f.set_obstacle(0.4, 0.5, 0.1)
        dt = 1.0 / 60.0
        for _ in range(30):
            f.simulate(dt, 0.0, 40, 1.9)
        for idx in range(len(f.u)):
            assert not math.isnan(f.u[idx]), "u contains NaN"
            assert not math.isinf(f.u[idx]), "u contains Inf"
        for idx in range(len(f.v)):
            assert not math.isnan(f.v[idx]), "v contains NaN"
            assert not math.isinf(f.v[idx]), "v contains Inf"
        max_vel = max(abs(f.u[i]) for i in range(len(f.u)))
        assert max_vel < 100.0, f"Velocity should be bounded, max|u| = {max_vel}"

    def test_flow_develops_around_obstacle(self):
        """Non-trivial velocity field develops downstream of the obstacle."""
        f = EulerianFluid(1000.0, 50, 50, 0.02)
        f.setup_wind_tunnel(2.0)
        f.set_obstacle(0.4, 0.5, 0.1)
        dt = 1.0 / 60.0
        for _ in range(20):
            f.simulate(dt, 0.0, 40, 1.9)
        n = f.numY
        h = f.h
        max_u = max(abs(f.u[idx]) for idx in range(len(f.u)))
        assert max_u > 0.5, f"Expected significant flow, max|u| = {max_u}"
        downstream_i = int(0.7 / h)
        has_downstream = any(
            abs(f.u[downstream_i * n + j]) > 0.1
            for j in range(n // 4, 3 * n // 4)
        )
        assert has_downstream, "Flow should exist downstream of obstacle"

    def test_smoke_propagates_from_inlet(self):
        """Smoke injected at the inlet propagates into the domain."""
        f = EulerianFluid(1000.0, 50, 50, 0.02)
        f.setup_wind_tunnel(2.0)
        f.set_obstacle(0.4, 0.5, 0.1)
        dt = 1.0 / 60.0
        for _ in range(20):
            f.simulate(dt, 0.0, 40, 1.9)
        n = f.numY
        found_smoke = any(
            f.m[i * n + j] < 0.9
            for i in range(1, 15)
            for j in range(1, n - 1)
        )
        assert found_smoke, "Smoke should propagate from inlet into domain"

    def test_smoke_conservation_approximate(self):
        """Total smoke in domain should increase over time as inlet injects smoke."""
        f = EulerianFluid(1000.0, 30, 30, 1.0 / 30)
        f.setup_wind_tunnel(1.5)
        dt = 1.0 / 60.0
        n = f.numY
        initial_smoke = sum(1.0 - f.m[i * n + j]
                            for i in range(1, f.numX - 1)
                            for j in range(1, n - 1))
        for _ in range(30):
            f.simulate(dt, 0.0, 40, 1.9)
        final_smoke = sum(1.0 - f.m[i * n + j]
                          for i in range(1, f.numX - 1)
                          for j in range(1, n - 1))
        assert final_smoke > initial_smoke, \
            f"Smoke should accumulate from inlet: initial={initial_smoke:.2f}, final={final_smoke:.2f}"
