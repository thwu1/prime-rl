An 8-thruster underwater ROV (HexaCross-8) at `/app/` has been experiencing anomalous behavior — unexpected drift, cross-axis coupling, and degraded controllability in certain degrees of freedom. The vehicle's frame parameters may contain errors introduced when thruster configuration was manually re-entered after a maintenance session.

The `/app/` directory contains:
- Telemetry recordings in a SQLite database (`/app/telemetry/flight_test.db`) with multiple test sessions across several tables in different schemas (commands stored per-thruster in long format, IMU data in a separate table)
- Thruster frame configuration in ArduPilot parameter format (`/app/config/frame.param`) using `MOT_*_POS_*` and `MOT_*_DIR_*` naming conventions
- Vehicle physical properties in URDF XML format (`/app/config/vehicle.urdf`)
- Thrust calibration data in a custom binary format (`/app/calibration/thrust_cal.dat`) with the format specification in `/app/calibration/FORMAT.md` — these coefficients are required to convert PWM command signals to actual force in Newtons
- Controller logs and maintenance notes in `/app/logs/` and `/app/mission_notes.txt`

The telemetry database contains recordings from several sessions — only the controlled thruster test session has data suitable for system identification. IMU-measured accelerations during known command inputs can be used to recover the true thruster-to-wrench mapping through the vehicle's rigid-body dynamics. The solver must extract and combine data from all four formats (SQLite, ArduPilot parameters, URDF XML, and binary calibration) to perform the identification.

Investigate the system, identify which thrusters have incorrect configuration parameters, determine the correct values, and assess the impact on vehicle controllability.

Produce `/app/diagnosis.json` containing:

- `faults` — array of objects, each identifying a misconfigured thruster with keys: `thruster_id` (int), `field` (string: `"direction"` or `"position"`), `incorrect` (3-element float list from current config), `correct` (3-element float list of actual values)
- `corrected_allocation_matrix` — the correct 6x8 thruster-to-wrench mapping as row-major list-of-lists
- `original_allocation_matrix` — the matrix derived from the current (faulty) configuration as row-major list-of-lists
- `corrected_condition_number` — 2-norm condition number of the corrected matrix (float)
- `original_condition_number` — 2-norm condition number of the original matrix (float)
- `corrected_rank` — rank of the corrected matrix (int)
- `controllability_restored` — whether full 6-DOF controllability is achieved with corrections (bool)

All float values rounded to 6 decimal places.