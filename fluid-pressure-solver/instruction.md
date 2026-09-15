A 2D incompressible fluid simulator at `/app/` uses a MAC staggered grid with the fractional-step method: semi-Lagrangian advection, gravity application, and pressure projection via PCG. Source modules are in `/app/fluid/`.

The simulator contains multiple numerical defects introduced during integration from a reference implementation. Running the dam-break scenario (`python3 /app/run_simulation.py` -- 32x32 grid, 50 time steps) produces non-physical results: velocity divergence, numerical blowup, or incorrect fluid motion.

Diagnose and fix all defects in `/app/fluid/` so the simulation satisfies:

- Velocity divergence below 1e-4 at every step
- Velocity magnitude below 10.0 throughout
- Kinetic energy monotonically increasing under gravity
- Stable completion of all 50 steps