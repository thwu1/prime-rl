A ROS2 Nav2 navigation stack configuration at `/app/nav2_params.yaml` contains 12 subtle bugs that cause a warehouse differential-drive robot to collide with obstacles, get stuck, or behave erratically. The bugs involve cross-component parameter interactions, physical constraint violations, and architectural misconfigurations across costmaps, the MPPI controller, velocity smoother, behavior tree navigator, collision monitor, and costmap filter info servers. Reference documentation is at `/app/docs/`.

Produce three artifacts:

**`/app/nav2_auditor.py`** -- A general-purpose Nav2 configuration auditor. Takes a YAML config path as its sole argument. Prints a JSON array to stdout where each element has keys `rule_id` (snake_case identifier), `severity` (`critical`, `error`, or `warning`), `component` (affected Nav2 node), and `description` (explanation including robot-behavior impact). Validation rules must be general -- not hardcoded to this specific file's values.

**`/app/nav2_params_fixed.yaml`** -- The corrected configuration with all 12 issues resolved. Preserve every valid setting and the overall YAML structure.

**`/app/audit_report.json`** -- Output of running your auditor against the original broken configuration.