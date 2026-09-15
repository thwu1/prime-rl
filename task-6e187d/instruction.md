A differential-drive warehouse robot using the ROS 2 Nav2 navigation stack is failing navigation tasks during integration testing. The Nav2 configuration is at `/app/nav2_params_broken.yaml` and the robot's hardware specification is at `/app/robot_spec.json`. Simulation test logs from the failing runs are at `/app/sim_logs/navigation_test.log`.

A previous engineer left a configuration validation script at `/app/tools/validate_nav2.py`. Its accuracy has not been independently verified — treat its output as one data source among several, not as ground truth.

The robot exhibits the following failure modes:

- Phantom obstacles accumulate in areas the robot has already traversed, causing it to treat open space as permanently blocked
- The robot cannot navigate through corridors it should physically fit through
- The global planner generates paths the local controller consistently fails to track
- Jerky, discontinuous motion with visible acceleration inconsistencies between planned and executed trajectories
- Oscillation and overshoot when approaching goal poses, with the robot cycling between competing objectives
- The robot occasionally attempts motions its drivetrain cannot physically execute
- The global planner appears unaware of dynamic obstacles that the local planner detects

Produce the following files:

1. `/app/diagnosis_report.json` — A JSON object with two keys:
   - `"config_issues"`: array of objects, each with `"id"` (snake_case), `"severity"` (`"critical"` or `"warning"`), `"description"` (root cause and affected parameter values), and `"evidence"` (array of strings citing specific log entries or configuration values that led to the finding).
   - `"environmental"`: array of objects, each with `"id"` (snake_case) and `"description"`, cataloging observations from the simulation logs that are NOT caused by configuration errors (e.g., transient sensor noise, normal operational telemetry).

2. `/app/nav2_params_fixed.yaml` — A corrected Nav2 configuration that resolves all identified configuration issues while satisfying the robot's physical constraints from the hardware specification.

3. `/app/parameter_justification.json` — A JSON object with a `"changes"` key containing an array of objects, each with `"parameter"` (dot-separated path to the changed parameter), `"old_value"`, `"new_value"`, and `"rationale"` (why this specific value was chosen, referencing the robot specification or inter-parameter constraints).