A baseline Extended Kalman Filter at `/app/pipeline/localize.py` estimates the trajectory of an Ackermann-steered vehicle using noisy control inputs and range-bearing landmark observations from `/app/sensor_data.db`. Vehicle and filter parameters are in `/app/config.json`.

The baseline filter is implemented correctly, but its position accuracy is significantly worse than what the sensor noise model should allow. One or more landmark transponders in the environment have been physically compromised, introducing systematic range measurement bias. The biases are subtle enough that individual observations appear normal under the filter's existing consistency checks, yet they accumulate to substantially degrade the state estimate over time.

Determine which landmarks are compromised and produce a localization pipeline that achieves the accuracy the sensor configuration should support. Write the following to `/app/output/`:

- `trajectory.csv` — columns: `timestep,x,y,theta` — corrected filter pose estimates (501 rows, timestep 0–500)
- `covariance.csv` — columns: `timestep,P00,P01,P02,P11,P12,P22` — upper-triangle 3x3 covariance (501 rows)
- `diagnosis.json` — keys: `compromised_landmarks` (list of integer landmark IDs), `evidence` (object mapping each compromised ID as string key to `{"mean_range_innovation": float, "num_observations": int, "p_value": float}` quantifying the evidence against each flagged landmark)
- `comparison.json` — keys: `baseline_position_rmse`, `robust_position_rmse`, `baseline_heading_rmse`, `robust_heading_rmse` (floats; position in meters, heading in radians; computed from timestep 50 onward against the `ground_truth` table in the database)
- `stats.json` — keys: `outliers_detected` (int), `total_observations` (int) from the corrected filter
- `trajectory_plot.png` — `gnuplot`-generated PNG showing corrected vs baseline x-y trajectories on the same axes

Create a table `filter_residuals` in `/app/sensor_data.db` with schema `(timestep INTEGER, landmark_id INTEGER, range_residual REAL, bearing_residual REAL, mahalanobis REAL, accepted INTEGER)` containing one row per observation processed by the corrected filter (`accepted` = 1 for inliers, 0 for rejected). Counts must be consistent with `stats.json`.

## Acceptance criteria

- Correctly identify ALL compromised landmarks with zero false positives; each with p_value < 0.01
- Position RMSE (x and y independently) below 0.5 m and heading RMSE below 0.15 rad from timestep 50 onward
- Corrected filter position RMSE at least 30% below baseline
- Mean NEES between 0.3 and 10.0 from timestep 50 onward
- Covariance positive-definite throughout; diagonal in (1e-10, 100.0) from timestep 50 onward
- No inter-step position jumps > 0.5 m or heading jumps > 0.4 rad
- `trajectory_plot.png` valid PNG at least 1 KB
- `filter_residuals` table: correct schema, >500 rows, binary accepted values, counts consistent with stats.json