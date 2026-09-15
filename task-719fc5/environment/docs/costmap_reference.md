# Costmap 2D Reference

## Plugin Loading Order

Costmap layers are loaded and processed in the order specified in the `plugins` parameter list. This ordering is critical:

- **Obstacle source layers** (StaticLayer, ObstacleLayer, VoxelLayer) populate the costmap with obstacle data from maps and sensors.
- **InflationLayer** expands obstacle costs radially outward, creating a gradient around obstacles.

If InflationLayer appears before obstacle source layers in the `plugins` list, inflation is applied to an empty/partial costmap. Obstacles added afterward will NOT have inflation applied, meaning the planner and controller see raw lethal costs without the critical safety gradient.

Correct ordering: obstacle sources first, then inflation.

## Inflation Radius vs. Robot Radius

The `inflation_radius` parameter defines how far obstacle costs are expanded outward. The `robot_radius` defines the robot's circular footprint radius.

**inflation_radius must be >= robot_radius.** If smaller, the inflated zone is narrower than the robot itself. The planner may compute paths that pass through the un-inflated zone, where the robot's body would collide with the actual obstacle.

## Robot Radius Consistency

The `robot_radius` parameter appears in both local_costmap and global_costmap. These should be identical since they represent the same physical robot. Inconsistencies cause the global planner to compute paths through spaces that the local controller considers impassable (or vice versa).

## Costmap Sizing and Controller Horizon

For local costmaps with `rolling_window: true`, the `width` and `height` define the costmap dimensions in meters. The costmap is centered on the robot, so the maximum visible distance is `width/2` (or `height/2`).

A predictive controller (like MPPI) projects trajectories forward by its prediction horizon. If the prediction distance (`time_steps * model_dt * vx_max`) exceeds the costmap half-width, trajectories are clipped at the costmap boundary, artificially limiting the robot's effective speed and trajectory quality.

## Layer Configuration vs. Plugin List

Each costmap layer must be:
1. **Configured** as a namespace under `ros__parameters` with a `plugin` parameter specifying the plugin class
2. **Listed** in either the `plugins` array (for regular layers) or `filters` array (for costmap filters)

A layer that is configured but not listed in either array will be silently ignored — it will not be loaded or applied.

## Costmap Filter Plugins

Costmap filters (KeepoutFilter, SpeedFilter) are distinct from regular costmap plugins. They are listed under the `filters` parameter and applied on top of the combined layered costmap. Each filter references a corresponding filter info server for its configuration.
