"""FLIP Fluid Simulator — Python ctypes wrapper around a C shared library.

Implement a FLIP fluid solver per the specification at /app/spec.md,
compile it as /app/libflip.so using the Makefile at /app/Makefile, and complete
this Python wrapper using the ctypes module.
"""

FLUID_CELL = 0
AIR_CELL = 1
SOLID_CELL = 2


class FlipFluid:
    """2D FLIP fluid simulator backed by a C shared library via ctypes.

    Required attributes after construction:
        numParticles      (int, read/write)
        particlePos       (indexable float array, length 2*maxParticles, read/write)
        particleVel       (indexable float array, length 2*maxParticles, read/write)
        h                 (float, read-only)
        fNumX             (int, read-only)
        fNumY             (int, read-only)
        fInvSpacing       (float, read-only)
        particleRadius    (float, read-only)
        u                 (indexable float array, length fNumCells, read)
        v                 (indexable float array, length fNumCells, read)
        s                 (indexable float array, length fNumCells, read/write)
        cellType          (indexable int array, length fNumCells, read)
        particleDensity   (indexable float array, length fNumCells, read)
        lastSubsteps      (int, read-only — substep count from most recent simulate)
        lastMaxDivergence (float, read-only — max |div| after last pressure solve)
        lastPressureIters (int, read-only — pressure iterations used in last solve)
    """

    def __init__(self, density, width, height, spacing, particle_radius, max_particles):
        raise NotImplementedError

    def simulate(self, dt, gravity, flip_ratio, num_pressure_iters,
                 num_particle_iters, over_relaxation, compensate_drift,
                 separate_particles):
        """Run one full simulation timestep with CFL-adaptive sub-stepping."""
        raise NotImplementedError
