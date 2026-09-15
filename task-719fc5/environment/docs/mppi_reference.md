# MPPI Controller Reference

## Motion Models

The MPPI controller supports three motion models. The `motion_model` parameter selects the model by name, and the corresponding namespace must contain a `plugin` parameter with the correct plugin class:

| motion_model | Plugin Class | Description |
|---|---|---|
| `"diff_drive"` | `mppi::DiffDriveMotionModel` | Differential drive — forward/reverse and rotation only, no lateral motion |
| `"omni"` | `mppi::OmniMotionModel` | Omnidirectional — full lateral motion capability |
| `"ackermann"` | `mppi::AckermannMotionModel` | Car-like — minimum turning radius constraint |

The `motion_model` name and the plugin class under its namespace must be consistent. A mismatch (e.g., `motion_model: "diff_drive"` with `plugin: "mppi::OmniMotionModel"`) will cause undefined behavior as the kinematic constraints won't match the trajectory generation.

## Prediction Horizon

The prediction horizon determines how far ahead the controller plans:
- **Prediction time** = `time_steps` x `model_dt` (seconds)
- **Maximum prediction distance** = `time_steps` x `model_dt` x `vx_max` (meters)

Example: time_steps=56, model_dt=0.05, vx_max=0.5 → 2.8 seconds, 1.4 meters

The local costmap must be large enough to contain the full prediction distance. If the costmap half-width is smaller than the prediction distance, the controller is artificially limited.

## Velocity Parameters

- `vx_max` / `vx_min`: Forward/reverse velocity bounds (m/s)
- `vy_max`: Lateral velocity bound (m/s) — only relevant for `omni` motion model
- `wz_max`: Angular velocity bound (rad/s)
- `vx_std`, `vy_std`, `wz_std`: Sampling standard deviations for trajectory generation

## Critics

MPPI uses plugin-based critic functions to score trajectories. Critics are listed in the `critics` parameter and configured in their respective namespaces. Key critics include:
- **ConstraintCritic**: Penalizes kinematic/dynamic constraint violations
- **CostCritic**: Penalizes proximity to obstacles using costmap values
- **GoalCritic/GoalAngleCritic**: Incentivizes reaching goal pose
- **PathAlignCritic**: Incentivizes alignment with the global path
- **PathFollowCritic**: Incentivizes progress along the path
- **PreferForwardCritic**: Penalizes reverse motion
