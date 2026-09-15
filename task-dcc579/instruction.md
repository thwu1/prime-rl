A simulated mobile robot navigates a 2D environment equipped with three sensor systems. Raw sensor data is in `/app/data/`:

- **Odometry** (`odometry.csv`): Linear velocity `v` and angular velocity `omega` at 10 Hz. Motion model is the standard unicycle: `x' = v*cos(theta)`, `y' = v*sin(theta)`, `theta' = omega`. Both channels suffer from Gaussian noise **and** a slowly-drifting additive bias.
- **GPS** (`gps.csv`): Position `(x, y)` at 1 Hz. Gaussian noise with sigma ~3 m, but approximately 15% of readings are gross outliers (offsets of 15–45 m).
- **Range-to-landmark** (`range_measurements.csv`): Euclidean distance to known landmarks at 2 Hz, maximum sensing range 25 m. Gaussian noise with sigma ~0.5 m, approximately 10% outliers (offsets of 10–30 m).

Landmark positions: `/app/data/landmarks.json`. Full noise parameters and rates: `/app/data/sensor_config.json`. The robot starts near the origin.

Implement `/app/estimator.py` — a Python script that accepts two positional command-line arguments (`data_directory` and `output_path`), reads the sensor data from the given directory, and writes the estimated robot trajectory as CSV with columns `time`, `x`, `y`, `theta` to the output path. Produce one output row per odometry timestep.

Requirements:
- Position RMSE below 1.5 m against ground truth on datasets generated with the same noise model but arbitrary random seeds.
- Properly reject sensor outliers to prevent estimate corruption.
- Work correctly on fresh datasets, not just the provided one.