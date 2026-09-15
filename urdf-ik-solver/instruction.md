A 6-DOF revolute robot arm is described by the URDF at `/app/robot.urdf`. The physical robot has small manufacturing deviations from the nominal URDF parameters. The file `/app/task_config.json` contains:

- `fk_tests`: Three joint configurations for which you must compute the nominal forward kinematics (position and 3x3 orientation matrix).
- `calibration_measurements`: 30 pairs of (joint_angles, measured_position) from the physical robot, with sub-millimeter measurement noise. Use these to identify systematic errors in the URDF kinematic parameters.
- `validation_measurements`: 5 held-out pairs for evaluating calibration quality. The calibrated model must reduce validation RMSE by at least 60% compared to the nominal model.
- `ik_targets`: 3 target end-effector positions. Solve inverse kinematics using the calibrated model, respecting URDF joint limits. Position error must be under 1 cm.
- `ik_with_orientation`: A target position with a desired end-effector Z-axis direction. Solve constrained IK for both position and orientation.
- `jacobian_config`: A joint configuration at which to compute the 6x6 geometric Jacobian, its rank, Yoshikawa manipulability index, and singular values.
- `workspace_samples`: Number of random FK samples for estimating the reachable workspace volume (convex hull, in m^3).

Write `/app/analyze.py` that reads the URDF and config, performs all analyses, and writes `/app/results.json` with these top-level keys:

- `nominal_fk`: dict mapping test name to `{"position": [x,y,z], "orientation": [[3x3]]}`.
- `calibration_stats`: `{"calibration_rmse": float, "validation_rmse": float, "nominal_validation_rmse": float}`.
- `calibrated_fk`: list of 5 dicts with `joint_angles`, `predicted_position`, `measured_position`, `position_error`.
- `ik_solutions`: list of 3 dicts with `name`, `target_position`, `joint_angles`, `achieved_position`, `position_error`.
- `ik_with_orientation`: dict with `name`, `target_position`, `target_orientation_z`, `joint_angles`, `achieved_position`, `achieved_z_axis`, `position_error`, `orientation_error`.
- `jacobian`: dict with `config`, `jacobian` (6x6 matrix), `rank`, `manipulability`, `singular_values`.
- `workspace_volume`: float (m^3).

You may only use the Python standard library plus numpy and scipy. No external robotics libraries (ikpy, roboticstoolbox, etc.) are allowed. The URDF uses RPY-rotated origins with all revolute axes along local Z.