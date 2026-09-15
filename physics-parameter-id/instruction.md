The directory `/app/` contains two JSON files:

- `/app/observations.json` — Recorded time-series trajectory data from three physics simulation experiments run in PyBullet (DIRECT mode, headless).
- `/app/experiment_config.json` — Complete configuration for each experiment: collision geometry, masses, initial conditions, simulation engine parameters, and documentation of the unknown parameters and how the simulation was constructed.

Each experiment was generated with a specific unknown physics parameter value. Your task is to identify these parameter values by building PyBullet simulations that reproduce the observed trajectories through parameter optimization.

The three experiments and their unknowns:
- **bouncing_sphere**: coefficient of restitution (applied identically to both sphere and ground)
- **sliding_block**: lateral friction coefficient (applied identically to both block and ground)
- **damped_pendulum**: viscous damping coefficient (applied as explicit external torque each simulation step — see config notes for the exact protocol)

Write the identified parameter values to `/app/results.json`:
```json
{
  "restitution": <float>,
  "lateral_friction": <float>,
  "joint_damping": <float>
}
```

Read `/app/experiment_config.json` carefully — it specifies every detail needed to reproduce each experiment exactly, including collision shapes, timestep, solver iterations, initial conditions, settling phases, and the damping torque application sequence. Verification is performed by re-simulating each experiment with your identified parameter values and comparing the resulting trajectory against the observation data.

PyBullet and NumPy are pre-installed in the environment.