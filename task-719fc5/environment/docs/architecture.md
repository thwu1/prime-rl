# Nav2 Architecture Reference

## Component Overview

Nav2 is a modular navigation stack for ROS2. Key components:

- **bt_navigator**: Orchestrates navigation using behavior trees. Sends action requests to planner_server and controller_server with a configurable `default_server_timeout`.
- **planner_server**: Computes global paths. Hosts the global costmap. Has a `costmap_update_timeout` that specifies how long to wait for the costmap to be ready.
- **controller_server**: Computes velocity commands to follow paths. Hosts the local costmap. Contains progress checkers and goal checkers.
- **velocity_smoother**: Smooths velocity commands from the controller, enforcing acceleration and velocity limits before passing to the robot.
- **collision_monitor**: Final safety layer that modifies or stops velocity commands to prevent collisions.
- **behavior_server**: Executes recovery behaviors (spin, backup, wait).

## Frame Consistency

All components that reference the robot's base frame must use the same frame ID. Components use different parameter names for this:
- `robot_base_frame` (costmaps, bt_navigator, behavior_server)
- `base_frame_id` (amcl, collision_monitor)

Mismatched frame IDs cause TF lookup failures, preventing components from determining the robot's position.

## Timeout Chain

The bt_navigator's `default_server_timeout` is how long the behavior tree waits for action server responses. This must be long enough to accommodate the planner_server's `costmap_update_timeout` and planning time. If the BT timeout is shorter, the behavior tree may abort before the planner finishes.

## Velocity Pipeline

Velocity commands flow through a pipeline:
1. controller_server computes commands (bounded by vx_max, wz_max, etc.)
2. velocity_smoother applies acceleration limits and velocity bounds (max_velocity, min_velocity)
3. collision_monitor applies safety modifications

If the velocity_smoother's limits are lower than the controller's, the smoother will clip commands, preventing the robot from reaching its configured maximum speeds. The smoother's velocity limits should be at least as large as the controller's.

## Progress and Goal Checking

The **progress checker** monitors whether the robot is making sufficient forward progress. Its `required_movement_radius` defines the minimum distance the robot must move within `movement_time_allowance` seconds.

The **goal checker** determines when the robot has reached its goal. Its `xy_goal_tolerance` defines the acceptable position error.

If `required_movement_radius` exceeds `xy_goal_tolerance`, the progress checker may report the robot as "stuck" when it is actually making small adjustments near the goal pose.
