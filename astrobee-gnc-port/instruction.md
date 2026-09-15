NASA's Astrobee free-flyer robot uses a GNC (Guidance, Navigation, and Control) controller written in C++ with Eigen. The production controller source code is provided at `/app/ctl_src.cc`, along with tuning parameters in `/app/gnc_config.txt`.

Your task: create `/app/astrobee_ctl_sim.py` that faithfully reproduces the behavior of this controller in Python, embeds it in a closed-loop rigid-body simulation of the free-floating robot, and produces numerical results for a set of predefined test scenarios.

## Provided Files

- `/app/ctl_src.cc` — The complete production controller implementation in C++/Eigen. Your Python port must match this code's behavior exactly.
- `/app/gnc_config.txt` — Controller tuning parameters (Lua format, for reference).
- `/app/scenarios.json` — Robot physical parameters, controller configuration, and six simulation scenarios with initial conditions and targets.

## Requirements

Your script must read `/app/scenarios.json`, run each scenario as a closed-loop simulation (controller + rigid-body plant dynamics), and write results to `/app/results.json`.

The output must be a JSON object keyed by scenario name. Each entry must contain:

```json
{
  "final_position": [x, y, z],
  "final_velocity": [vx, vy, vz],
  "final_quaternion": [qx, qy, qz, qw],
  "final_omega": [wx, wy, wz],
  "step_1_force": [fx, fy, fz],
  "step_1_torque": [tx, ty, tz]
}
```

`step_1_force` and `step_1_torque` are the body-frame controller outputs from the very first simulation step. `final_*` values are the plant state after the last integration step of each scenario.