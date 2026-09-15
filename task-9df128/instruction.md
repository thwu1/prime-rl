A warehouse is migrating from a differential-drive robot to an Ackermann-steered AGV. The new robot's physical specifications are in `/app/robot_spec.yaml`. The current Nav2 MPPI controller configuration at `/app/nav2_params.yaml` and behavior tree at `/app/nav2_bt.xml` were configured for the old differential-drive platform.

A previous engineer attempted a partial migration and left `/app/validate_config.py` and `/app/migration_notes.md`. Both contain errors — do not trust them without independent verification.

The fleet operations database `/app/fleet.db` (SQLite) contains deployment history, platform specifications, and incident reports from previous Ackermann migrations across the warehouse fleet.

Produce a corrected Nav2 configuration that is physically valid and internally consistent for the new Ackermann AGV. Every parameter that depends on the platform's kinematic model, physical geometry, or motion capabilities must be correct for the vehicle described in the robot specification. The full velocity command pipeline must be consistent end-to-end. The behavior tree must only contain recovery actions that are physically achievable by the vehicle.

Protected parameters (do not modify): `time_steps`, `model_dt`, `controller_frequency`, costmap `resolution`.

Write the following deliverables:
- Corrected `/app/nav2_params.yaml`
- Corrected `/app/nav2_bt.xml`
- `/app/audit.json` — a JSON array documenting all issues found and corrected. Each entry must have exactly five fields: `"file"` (filename), `"path"` (dot-separated parameter location), `"old"` (original value), `"new"` (corrected value), and `"reason"` (physical or geometric justification, minimum 5 words). Minimum 10 entries. Every `old`/`new` pair must differ.