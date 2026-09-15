A simulation of a spatial (3D) double pendulum is provided at `/app/`. The system models two rigid links connected by spherical joints under gravity, using an index-3 DAE formulation with Euler parameters (quaternions) for orientation.

The simulation is non-functional due to multiple issues across the Python and C codebase. Fix all issues so that `cd /app && python3 run_simulation.py` completes a 10-second simulation producing physically correct results.

## Native Constraint Library

The simulation depends on a C shared library at `/app/native/libconstraints.so` for constraint Jacobian evaluation, loaded via Python `ctypes` at runtime. The source code and Makefile are in `/app/native/`, but the build configuration has errors that prevent producing a loadable shared library. The native code itself may also contain computational errors.

## Output Files

The simulation must produce:
- `/app/results/simulation_results.json` — JSON object containing keys: `completed` (bool), `n_steps_completed` (int), `n_steps_total` (int), `initial_energy` (float), `final_energy` (float), `max_constraint_violation` (float), `avg_newton_iterations` (float)
- `/app/results/trajectories.npz` — NumPy archive containing arrays: `times`, `energies`, `constraint_violations`, `positions_link1`, `positions_link2`, `quat_norms_1`, `quat_norms_2`

## Success Criteria

- All 10000 timesteps complete without solver failure
- Maximum constraint violation < 1e-6 at every recorded timestep
- Total mechanical energy conserved within 2% relative error throughout
- Initial and final energy magnitudes > 0.01 J
- Average solver iterations per step: 1 ≤ avg ≤ 10
- Quaternion norms for both links stay within 1e-4 of unity
- Link center-of-mass positions bounded (< 3m from origin) and non-stationary
- Trajectory covers the full 10 seconds (t_final ≥ 9.99s)
- `/app/native/libconstraints.so` must exist and provide correct constraint Jacobian evaluation
- The integrator's assembled linear system must have full rank