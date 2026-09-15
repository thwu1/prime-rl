A KUKA youBot mobile manipulator (4-mecanum-wheel omnidirectional base + 5-DOF serial arm) is described in URDF at `/app/youbot.urdf`. Simulation parameters and a target end-effector pose are in `/app/task_spec.yaml`.

Create `/app/youbot_controller.py` that parses the URDF to extract all kinematic parameters (no hardcoded values) and exports the following functions:

- `next_state(config, controls, dt, speed_limit)` → updated 12-vector.
  `config` = `[phi, x, y, theta1..5, wheel1..4]` (chassis heading, x, y, 5 arm joint angles, 4 wheel angles).
  `controls` = `[u1..4, dtheta1..5]` (4 wheel speeds, 5 arm joint speeds), all clamped to `[-speed_limit, speed_limit]`.
  Returns the new configuration after one timestep of duration `dt`.

- `compute_end_effector_config(config)` → 4×4 SE(3) homogeneous transform of the end-effector in the space frame.

- `mobile_manipulator_jacobian(config)` → 6×9 Jacobian mapping the 9-vector `[u1..4, dtheta1..5]` to the end-effector body twist.

- `feedback_control(X, Xd, Xd_next, Kp, Ki, error_integral, dt)` → `(V, Xerr, updated_integral)`.
  `X`, `Xd`, `Xd_next`: 4×4 SE(3) current, desired, and next-timestep desired poses.
  `Kp`, `Ki`: 6×6 gain matrices. `error_integral`: 6-vector accumulator.
  Returns commanded body twist `V`, the 6-vector task-space error `Xerr`, and updated integral.

- `compute_controls(V, config)` → 9-vector of controls that best realize body twist `V` given the current `config`.

Only `numpy` and the Python standard library may be used — no `modern_robotics` or other robotics/kinematics libraries.

Using the parameters from `/app/task_spec.yaml`, run a closed-loop simulation that drives the end-effector to the target pose, producing:

- `/app/error_data.csv` — header `step,wx,wy,wz,vx,vy,vz`, one row per timestep with the 6 error-twist components.
- `/app/error_plot.png` — convergence plot of all six error components vs. timestep, generated with `gnuplot`.