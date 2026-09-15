A quadrotor simulation pipeline at `/app/` is producing trajectories that diverge significantly from recorded flight data. The pipeline contains at least one implementation bug and uses physical parameter values that may be inaccurate. Your task is to identify and correct all sources of error — both code defects and parameter inaccuracies — so the simulation accurately reproduces the recorded trajectory.

## Environment

- `/app/simulator.py` — quadrotor dynamics simulator (known to produce divergent results; compare against the reference spec to find implementation errors)
- `/app/data/flight_data.npz` — ground-truth flight recording (2 s at 500 Hz). Arrays: `timestamps` (1001,), `positions` (1001, 3), `velocities` (1001, 3), `quaternions` (1001, 4) in scalar-last `[x, y, z, w]` convention, `angular_velocities` (1001, 3) in body frame, `motor_rpms` (1000, 4)
- `/app/data/known_params.json` — verified geometric and inertial parameters (`arm_length`, `Ixx`, `Iyy`, `Izz`, `g`)
- `/app/data/sim_params.json` — the simulator's current physical parameters (`mass`, `kf`, `kt`), which may be inaccurate
- `/app/dynamics_spec.md` — reference first-principles dynamics model specification defining the correct equations, quaternion convention, motor layout, and mixing matrix

## Output

Save the corrected physical parameters as JSON to `/app/results/params.json` with exactly three numeric keys:

- `mass` — drone mass in kg
- `kf` — thrust coefficient in N/RPM²
- `kt` — torque coefficient in N·m/RPM²

All values must be positive and finite.

## Acceptance criteria

1. **Parameter accuracy**: each recovered parameter must be within relative tolerance of the true physical value — mass ≤ 5%, kf ≤ 8%, kt ≤ 15%.
2. **Physical consistency**: derived hover RPM `sqrt(mass * g / (4 * kf))` must be in [5000, 30000]. The ratio `kt / kf` must be in [0.005, 0.1].
3. **Trajectory fidelity**: a 100-step forward simulation from the initial recorded state, using the corrected parameters with the dynamics specified in `/app/dynamics_spec.md`, must match recorded positions with mean error < 0.02 m and max error < 0.10 m.