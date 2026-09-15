Recorded flight trajectories from a Crazyflie-class quadrotor with unknown physical parameters are stored in `/app/data/training/` (5 flights, 1.5 s each) and `/app/data/validation/` (3 flights, 1.0 s each). Each `.npz` file contains timestamped motor commands (`commands`), the full initial state (`initial_pos`, `initial_quat`, `initial_vel`, `initial_ang_vel`, `initial_rotor_vel`), and the recorded trajectory (`positions`, `quaternions`). Linear and angular velocities are **not** recorded after the initial instant.

The drone's mass (0.033 kg), arm length (0.046 m), gravity, timestep, and motor layout are known; see `/app/config.json`. The complete dynamics equations governing the system are documented in `/app/equations.md`.

Identify the 7 unknown physical parameters of the system: `Ixx`, `Iyy`, `Izz`, `kf`, `km`, `drag`, `motor_tau`.

## Required outputs

1. **`/app/identified_params.json`** — JSON object mapping each of the 7 parameter names to their identified numeric values.

2. **`/app/model.py`** — Python module exposing a `simulate` function with the following signature:

```python
def simulate(params_dict, initial_state_dict, commands, dt, n_steps):
    """Forward-simulate quadrotor dynamics.

    Args:
        params_dict: dict with float values for Ixx, Iyy, Izz, kf, km, drag, motor_tau, mass, L, g
        initial_state_dict: dict with arrays — pos(3,), quat(4,), vel(3,), ang_vel(3,), rotor_vel(4,)
        commands: array (n_steps, 4) of commanded RPMs
        dt: float timestep
        n_steps: int
    Returns:
        dict with keys positions(n_steps,3), quaternions(n_steps,4),
             velocities(n_steps,3), angular_velocities(n_steps,3)
    """
```

Each identified parameter must be within 10% of the true value. The model must predict validation trajectories with position RMSE < 0.15 m.