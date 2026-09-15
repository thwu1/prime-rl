# AGV Migration Notes
## Warehouse Robotics Team - J. Rivera

### Platform change: differential-drive to Ackermann AGV

Robot specification updated in robot_spec.yaml with new AGV dimensions and kinematics.

### Migration checklist:
1. ~~Switch motion_model to "ackermann"~~ — Added ackermann section under FollowPath, still need to update plugin name
2. Set vy_max to small positive value (0.1) for stability during sharp turns — don't set to zero or trajectory sampling may degenerate
3. Inflation radius: ensure >= inscribed_radius (0.20m) for safety clearance — already bumped to 0.25
4. Costmap size (3x3) adequate for warehouse corridors at current speed
5. near_collision_cost at 300 provides good safety margin above lethal threshold

### Notes:
- validate_config.py passes all checks on current config
- Velocity smoother auto-adapts to controller limits, no manual sync needed
- Collision monitor topics use default pipeline configuration
- ay_max/ay_min left as-is for controller sampling stability
