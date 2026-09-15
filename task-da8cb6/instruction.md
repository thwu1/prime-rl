Four drive actuators (A, B, C, D) implement dynamics based on the four-stage pipeline described in `/app/actuator_model_spec.md`. Each actuator has unique parameter values. The physical implementation of each actuator's internal stage ordering may not match the reference specification — validate the pipeline structure for each actuator against the measured data.

For each actuator, three step response measurements (small, medium, large amplitude; step from rest at t=0.5s) are provided at 100 Hz with realistic measurement noise. A novel command profile is provided for each actuator.

Determine the four pipeline parameters for each actuator, validate the pipeline stage ordering, and predict each actuator's response to its novel command profile.

## Data

- `/app/actuator_model_spec.md` — reference pipeline specification
- `/app/data/config_{A,B,C,D}_{small,medium,large}_step.csv` — step responses (time, command, response)
- `/app/data/novel_command_{A,B,C,D}.csv` — novel commands (time, command)

## Output

Write all outputs to `/app/output/`:

- `identified_params.json` — identified parameters per actuator:
  `{"A": {"dead_time": float, "time_constant": float, "max_acceleration": float, "max_velocity": float}, "B": {...}, "C": {...}, "D": {...}}`

- `pipeline_config.json` — validated pipeline stage ordering per actuator. Each entry is a list of the four stage names in their correct processing order:
  `{"A": ["dead_time", "velocity_saturation", "lpf", "acceleration_limit"], ...}`
  Stage names: `"dead_time"`, `"velocity_saturation"`, `"lpf"`, `"acceleration_limit"`

- `novel_response_{A,B,C,D}.csv` — predicted responses (time, response) at matching time points

- `calibration_rmse.json` — model fit quality per actuator per step size:
  `{"A": {"small": float, "medium": float, "large": float}, ...}`
  RMSE between your identified model's prediction and the measured step response data.

Parameters must match within engineering tolerance. Novel response RMSE must be < 0.15 m/s versus ground truth. Pipeline ordering must be correctly identified for all actuators.