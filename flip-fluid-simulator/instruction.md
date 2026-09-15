Implement a 2D incompressible fluid simulator as a C shared library with Python `ctypes` bindings. A mathematical specification of the base simulation pipeline is at `/app/spec.md`. A JavaScript reference implementation (without the extensions described below) is at `/app/flip_reference.js`. A Python stub defining the required class interface is at `/app/flip_sim.py`.

## Deliverables (all under `/app/`)

- **`flip_core.c`** — C implementation with all simulation state managed behind an opaque handle. Must export these symbols: `flip_create`, `flip_simulate`, `flip_destroy`, `flip_get_last_substeps`, `flip_get_last_max_divergence`, `flip_get_last_pressure_iters`, plus accessor functions for every attribute in the Python stub.
- **`Makefile`** — compiles `flip_core.c` into `libflip.so` (position-independent, linked against `libm`).
- **`flip_sim.py`** — Complete the Python wrapper using `ctypes` to load `libflip.so` and expose the `FlipFluid` class with all attributes listed in the stub, including diagnostic properties: `lastSubsteps` (int), `lastMaxDivergence` (float), `lastPressureIters` (int).

## Required Extensions

The reference implementation and the base specification lack these features. Your implementation must include both:

1. **Adaptive timestep subdivision**: `simulate` must assess whether current particle velocities risk numerical instability for the given timestep and grid spacing. When instability is possible, automatically subdivide the timestep into multiple substeps, each running the full simulation pipeline. When particles are slow or stationary with a small timestep, exactly 1 substep must be used. Expose the substep count from the most recent call via a read-only `lastSubsteps` attribute.

2. **Pressure solver convergence monitoring with early termination**: After each complete sweep of the pressure solver, evaluate the maximum absolute velocity divergence across all fluid cells. If this residual drops below 1×10⁻⁶, terminate the solver early. After the solver finishes (either by convergence or by reaching the iteration limit), expose:
   - `lastMaxDivergence`: the final residual (non-negative float, expected to be small after sufficient iterations)
   - `lastPressureIters`: number of iterations actually performed (must be ≥ 1; strictly less than the requested maximum when convergence is achieved)

## Physical Correctness Requirements

The simulator must satisfy all of the following:

- **Particle conservation**: the number of active particles remains exactly constant across all timesteps.
- **Boundary containment**: all particles remain within the domain boundaries after stepping.
- **Numerical stability**: particle velocities remain bounded (do not diverge) over extended simulation runs.
- **Incompressibility**: the velocity field at fluid cells is approximately divergence-free after pressure solving.
- **Gravity response**: starting from rest, applying gravity produces nonzero particle velocities and observable displacement across multiple timesteps.
- **Dam-break spreading**: particles initially concentrated on one side of a wider domain spread horizontally under gravity over multiple timesteps (mean x-position increases).

## Interface Constants

Cell type constants used in the Python module:
- `FLUID_CELL = 0`
- `AIR_CELL = 1`
- `SOLID_CELL = 2`

Run `make` in `/app/` to compile before testing.