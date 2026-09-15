A 6-DOF serial manipulator ("RBX-600") is described in `/app/robot.urdf`. The kinematic chain runs from `base_link` through six revolute joints to the `tool0` link frame; ignore links beyond `tool0`. The URDF includes full inertial parameters (mass, center-of-mass offsets) for every link in the chain, and effort limits for every revolute joint.

Perform a combined kinematic and static-dynamic analysis against the waypoints in `/app/waypoints.json` using parameters from `/app/config.json`. Produce two mutually consistent output files.

## `/app/results.json`

```json
{
  "fk_verification": {
    "q_zero": [[4x4 matrix]], "q_test1": [...], "q_test2": [...]
  },
  "waypoint_analysis": [
    {
      "id": 1,
      "reachable": true,
      "ik_solution": [q1, q2, q3, q4, q5, q6],
      "manipulability": 0.0123,
      "condition_number": 45.6,
      "near_singular": false,
      "gravity_torques": [tau1, tau2, tau3, tau4, tau5, tau6],
      "max_payload_kg": 12.5
    }
  ],
  "trajectory_segments": [
    {
      "from_id": 1, "to_id": 2,
      "min_manipulability": 0.005,
      "max_torque_ratio": 0.45,
      "dynamically_feasible": true,
      "feasible": true
    }
  ]
}
```

## `/app/analysis.db` (SQLite)

- `fk_results(config_name TEXT PRIMARY KEY, row0 TEXT, row1 TEXT, row2 TEXT, row3 TEXT)` — each row is a JSON array of 4 floats
- `waypoint_analysis(id INTEGER PRIMARY KEY, reachable INTEGER, ik_solution TEXT, manipulability REAL, condition_number REAL, near_singular INTEGER, gravity_torques TEXT, max_payload_kg REAL)` — `ik_solution` and `gravity_torques` are JSON arrays; NULL for unreachable waypoints
- `trajectory_segments(from_id INTEGER, to_id INTEGER, min_manipulability REAL, max_torque_ratio REAL, dynamically_feasible INTEGER, feasible INTEGER)`

## Requirements

**Forward kinematics**: Compute the 4×4 homogeneous transform from `base_link` to `tool0` for each test configuration listed in the config file.

**Waypoint analysis**: For each waypoint, determine reachability — whether a valid inverse kinematics solution exists within the robot's joint limits and within the `tolerance` specified in config. For reachable waypoints, report:
- `manipulability`: Yoshikawa's manipulability index at the solved configuration
- `condition_number`: kinematic condition number of the Jacobian
- `near_singular`: whether the configuration is near-singular per `manipulability_threshold` in config
- `gravity_torques`: the 6-element vector of joint torques required for static equilibrium under gravity at the solved configuration
- `max_payload_kg`: the maximum point-mass payload attachable at `tool0` such that all joints remain within their effort limits under static gravity loading

Unreachable waypoints: all IK-dependent fields are `null`/`NULL`.

**Trajectory segments**: For each pair of consecutive reachable, non-singular waypoints (ascending by ID), perform smooth joint-space interpolation with `num_samples` sample points, ensuring zero-velocity and zero-acceleration boundary conditions. Report:
- `min_manipulability`: minimum manipulability along the interpolated path
- `max_torque_ratio`: peak ratio of static gravity torque magnitude to effort limit, across all joints and all samples
- `dynamically_feasible`: true iff all static gravity torques along the path remain within effort limits
- `feasible`: true iff the segment is both kinematically non-singular and dynamically feasible

Euler convention per the waypoints file. Both output files must contain consistent data.