
"""Physical correctness and diagnostic tests for the FLIP fluid simulator."""

import sys
import math

sys.path.insert(0, "/app")

from flip_sim import FlipFluid, FLUID_CELL, AIR_CELL, SOLID_CELL


# ---------------------------------------------------------------------------
# Scenario helpers
# ---------------------------------------------------------------------------

def _create_tank(res=12, fill_frac=0.6, tank_width=1.0, tank_height=1.0):
    """Create a closed tank with particles filling the bottom portion."""
    spacing = tank_height / res
    density = 1000.0
    r = 0.3 * spacing
    dx_p = 2.0 * r
    dy_p = math.sqrt(3.0) / 2.0 * dx_p

    fNX = int(tank_width / spacing) + 1
    fNY = int(tank_height / spacing) + 1
    h = max(tank_width / fNX, tank_height / fNY)

    numX = int((tank_width - 2 * h - 2 * r) / dx_p)
    numY = int((fill_frac * tank_height - 2 * h - 2 * r) / dy_p)
    assert numX > 0 and numY > 0, "Grid too coarse for particles"

    f = FlipFluid(density, tank_width, tank_height, spacing, r, numX * numY)
    f.numParticles = numX * numY

    p = 0
    for i in range(numX):
        for j in range(numY):
            f.particlePos[p] = h + r + dx_p * i + (r if j % 2 else 0.0)
            p += 1
            f.particlePos[p] = h + r + dy_p * j
            p += 1

    n = f.fNumY
    for i in range(f.fNumX):
        for j in range(f.fNumY):
            s = 1.0
            if i == 0 or i == f.fNumX - 1 or j == 0:
                s = 0.0
            f.s[i * n + j] = s

    return f


def _create_dam_break(res=12):
    """Create a dam-break scenario: particles in the left 40% of a wide tank."""
    tank_width = 2.0
    tank_height = 1.0
    spacing = tank_height / res
    density = 1000.0
    r = 0.3 * spacing
    dx_p = 2.0 * r
    dy_p = math.sqrt(3.0) / 2.0 * dx_p

    fNX = int(tank_width / spacing) + 1
    fNY = int(tank_height / spacing) + 1
    h = max(tank_width / fNX, tank_height / fNY)

    water_w = 0.4 * tank_width
    water_h = 0.8 * tank_height
    numX = int((water_w - 2 * h - 2 * r) / dx_p)
    numY = int((water_h - 2 * h - 2 * r) / dy_p)
    assert numX > 0 and numY > 0

    f = FlipFluid(density, tank_width, tank_height, spacing, r, numX * numY)
    f.numParticles = numX * numY

    p = 0
    for i in range(numX):
        for j in range(numY):
            f.particlePos[p] = h + r + dx_p * i + (r if j % 2 else 0.0)
            p += 1
            f.particlePos[p] = h + r + dy_p * j
            p += 1

    n = f.fNumY
    for i in range(f.fNumX):
        for j in range(f.fNumY):
            s = 1.0
            if i == 0 or i == f.fNumX - 1 or j == 0:
                s = 0.0
            f.s[i * n + j] = s

    return f


# ---------------------------------------------------------------------------
# Core physics tests
# ---------------------------------------------------------------------------

class TestParticleConservation:
    """Particle count must remain constant throughout the simulation."""

    def test_count_unchanged(self):
        f = _create_tank(res=12, fill_frac=0.5)
        n0 = f.numParticles
        assert n0 > 0, "No particles created"

        for _ in range(10):
            f.simulate(1.0 / 60, -9.81, 0.9, 50, 2, 1.9, True, True)

        assert f.numParticles == n0, (
            f"Particle count changed from {n0} to {f.numParticles}"
        )


class TestBoundaryContainment:
    """All particles must stay inside the valid domain after simulation."""

    def test_particles_in_bounds(self):
        f = _create_tank(res=12, fill_frac=0.6)
        for _ in range(10):
            f.simulate(1.0 / 60, -9.81, 0.9, 50, 2, 1.9, True, True)

        h = f.h
        r = f.particleRadius
        eps = 0.02
        for i in range(f.numParticles):
            x = f.particlePos[2 * i]
            y = f.particlePos[2 * i + 1]
            assert x >= h + r - eps, (
                f"Particle {i} violates left boundary: x={x:.6f}"
            )
            assert x <= (f.fNumX - 1) * h - r + eps, (
                f"Particle {i} violates right boundary: x={x:.6f}"
            )
            assert y >= h + r - eps, (
                f"Particle {i} violates bottom boundary: y={y:.6f}"
            )


class TestStability:
    """The simulation should not blow up over 20 timesteps."""

    def test_velocities_bounded(self):
        f = _create_tank(res=12, fill_frac=0.6)
        for _ in range(20):
            f.simulate(1.0 / 60, -9.81, 0.9, 50, 2, 1.9, True, True)

        max_vel = 0.0
        for i in range(f.numParticles):
            vx = abs(f.particleVel[2 * i])
            vy = abs(f.particleVel[2 * i + 1])
            if vx > max_vel:
                max_vel = vx
            if vy > max_vel:
                max_vel = vy

        assert max_vel < 50.0, (
            f"Simulation unstable: max velocity {max_vel:.2f} exceeds 50"
        )


class TestDivergenceFree:
    """After pressure projection the velocity field should be nearly
    divergence-free at fluid cells."""

    def test_max_divergence(self):
        f = _create_tank(res=12, fill_frac=0.6)
        f.simulate(1.0 / 60, -9.81, 0.9, 100, 2, 1.9, False, True)

        n = f.fNumY
        max_div = 0.0
        num_fluid = 0
        for i in range(1, f.fNumX - 1):
            for j in range(1, f.fNumY - 1):
                if f.cellType[i * n + j] != FLUID_CELL:
                    continue
                right = (i + 1) * n + j
                top = i * n + j + 1
                center = i * n + j
                div = (f.u[right] - f.u[center] +
                       f.v[top] - f.v[center])
                ad = abs(div)
                if ad > max_div:
                    max_div = ad
                num_fluid += 1

        assert num_fluid > 0, "No fluid cells found after simulation step"
        assert max_div < 0.01, (
            f"Velocity field not divergence-free: max |div| = {max_div:.6f} "
            f"over {num_fluid} fluid cells"
        )


class TestGravityEffect:
    """Gravity must produce nonzero velocities and move particles."""

    def test_particles_move_under_gravity(self):
        f = _create_tank(res=12, fill_frac=0.6)

        total_v0 = sum(abs(f.particleVel[2 * i]) + abs(f.particleVel[2 * i + 1])
                       for i in range(f.numParticles))
        assert total_v0 == 0.0, "Initial velocities should be zero"

        f.simulate(1.0 / 60, -9.81, 0.9, 50, 2, 1.9, True, True)

        max_vel = max(
            abs(f.particleVel[2 * i]) + abs(f.particleVel[2 * i + 1])
            for i in range(f.numParticles)
        )
        assert max_vel > 1e-4, (
            f"After one step with gravity, particles must have nonzero "
            f"velocity: max |v| = {max_vel:.8f}"
        )

        pos_snapshot = [f.particlePos[k] for k in range(2 * f.numParticles)]
        for _ in range(5):
            f.simulate(1.0 / 60, -9.81, 0.9, 50, 2, 1.9, True, True)

        max_disp = max(
            abs(f.particlePos[k] - pos_snapshot[k])
            for k in range(2 * f.numParticles)
        )
        assert max_disp > 1e-4, (
            f"Particles should move over multiple timesteps: "
            f"max displacement = {max_disp:.8f}"
        )


class TestDamBreakSpreading:
    """In a dam-break scenario, water should spread horizontally."""

    def test_mean_x_increases(self):
        f = _create_dam_break(res=12)
        mean_x0 = (sum(f.particlePos[2 * i]
                       for i in range(f.numParticles))
                   / f.numParticles)

        for _ in range(15):
            f.simulate(1.0 / 60, -9.81, 0.9, 50, 2, 1.9, True, True)

        mean_x1 = (sum(f.particlePos[2 * i]
                       for i in range(f.numParticles))
                   / f.numParticles)

        assert mean_x1 > mean_x0 + 0.01, (
            f"Dam-break should spread rightward: "
            f"mean_x {mean_x0:.4f} -> {mean_x1:.4f}"
        )


# ---------------------------------------------------------------------------
# CFL sub-stepping and diagnostic tests
# ---------------------------------------------------------------------------

class TestCFLSubstepping:
    """CFL-based adaptive sub-stepping must subdivide large timesteps."""

    def test_substeps_activate_high_velocity(self):
        f = _create_tank(res=12, fill_frac=0.5)
        # Inject high horizontal velocity to force CFL > 1
        for i in range(f.numParticles):
            f.particleVel[2 * i] = 5.0
        # CFL = 5.0 * 0.05 / h ~ 3.2 -> should need multiple substeps
        f.simulate(0.05, -9.81, 0.9, 50, 2, 1.9, True, True)
        assert f.lastSubsteps > 1, (
            f"High velocity should trigger CFL sub-stepping, "
            f"got {f.lastSubsteps} substeps"
        )

    def test_single_substep_when_slow(self):
        f = _create_tank(res=12, fill_frac=0.3)
        # All velocities zero, no gravity, tiny dt
        f.simulate(1e-4, 0.0, 0.9, 50, 2, 1.9, True, True)
        assert f.lastSubsteps == 1, (
            f"Zero-velocity with tiny dt should use 1 substep, "
            f"got {f.lastSubsteps}"
        )


class TestDivergenceReporting:
    """Post-solve max divergence must be reported and small."""

    def test_divergence_value(self):
        f = _create_tank(res=12, fill_frac=0.6)
        f.simulate(1.0 / 60, -9.81, 0.9, 100, 2, 1.9, False, True)
        div = f.lastMaxDivergence
        assert isinstance(div, float), "lastMaxDivergence must be a float"
        assert div >= 0.0, "Divergence should be non-negative"
        assert div < 0.01, (
            f"Max divergence should be small after 100 iters, got {div:.8f}"
        )


class TestPressureConvergence:
    """Pressure solver should terminate early when converged."""

    def test_early_exit(self):
        f = _create_tank(res=12, fill_frac=0.6)
        max_iters = 500
        f.simulate(1.0 / 60, -9.81, 0.9, max_iters, 2, 1.9, False, True)
        iters = f.lastPressureIters
        assert iters > 0, "Must perform at least one pressure iteration"
        assert iters < max_iters, (
            f"Solver should converge before {max_iters} iterations, "
            f"used {iters}"
        )


# ---------------------------------------------------------------------------
# Build artifact tests
# ---------------------------------------------------------------------------

class TestSharedLibraryExists:
    """The solution must compile flip_core.c into libflip.so via make."""

    def test_libflip_loadable(self):
        import ctypes
        import os
        lib_path = os.path.join("/app", "libflip.so")
        assert os.path.exists(lib_path), (
            "libflip.so not found at /app/libflip.so — run 'make' in /app/"
        )
        lib = ctypes.CDLL(lib_path)
        # Core symbols
        assert hasattr(lib, "flip_create"), "flip_create not found"
        assert hasattr(lib, "flip_simulate"), "flip_simulate not found"
        assert hasattr(lib, "flip_destroy"), "flip_destroy not found"
        # Diagnostic symbols
        assert hasattr(lib, "flip_get_last_substeps"), (
            "flip_get_last_substeps not found"
        )
        assert hasattr(lib, "flip_get_last_max_divergence"), (
            "flip_get_last_max_divergence not found"
        )
        assert hasattr(lib, "flip_get_last_pressure_iters"), (
            "flip_get_last_pressure_iters not found"
        )


class TestMakefileExists:
    """A Makefile must exist and produce libflip.so."""

    def test_makefile_present(self):
        import os
        assert os.path.exists("/app/Makefile"), "Makefile not found"

    def test_flip_core_c_present(self):
        import os
        assert os.path.exists("/app/flip_core.c"), "flip_core.c not found"
