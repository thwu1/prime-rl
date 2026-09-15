A 3D rotation processing pipeline at `/app/` requires debugging, algorithm implementation, and calibration analysis.

`/app/rotation_lib.py` is a PyTorch-based rotation conversion library supporting quaternions (w,x,y,z real-part-first), rotation matrices (3x3), Euler angles (intrinsic conventions), axis-angle vectors, and 6D rotation vectors (Zhou et al. CVPR 2019). Several conversion functions contain mathematical bugs that produce incorrect results. You must identify and fix all bugs so that every conversion is numerically correct, all roundtrips are consistent to within 1e-4 tolerance, and all output rotation matrices are proper rotations (orthogonal, det=+1).

`/app/rotation_analysis.py` provides three function stubs that must be implemented:
- `geodesic_distance(R1, R2)`: Returns the SO(3) geodesic distance between pairs of rotation matrices.
- `slerp(q1, q2, t)`: Interpolates between unit quaternions along the shortest great-circle path. Must return valid unit quaternions for all inputs including edge cases.
- `karcher_mean(quaternions, max_iter, tol)`: Computes the Fréchet mean of a set of rotations on SO(3). Must converge for clustered rotations and always return a unit quaternion.

`/app/sensor_data.json` contains rotation measurements from five virtual sensors, each reporting in a different representation format. `/app/analysis_config.toml` specifies calibration parameters.

Build a calibration pipeline that reads `/app/sensor_data.json` and `/app/analysis_config.toml`, converts each sensor's measurements to a common representation using the fixed rotation library, and produces:

- `/app/calibration_report.json` with fields: `overall_mean_quaternion` (4 floats), `sensor_rankings` (sensor IDs ordered by ascending mean geodesic distance from the overall mean), `per_sensor_stats` (dict mapping sensor_id to `{mean_geodesic_distance, max_geodesic_distance, individual_mean_quaternion}`), and `slerp_trajectory` containing `{from_sensor, to_sensor, quaternions}` — an interpolation between the best and worst sensors' individual means using the `num_steps` parameter from the config.
- `/app/sensor_diagnostic.png` — a bar chart comparing per-sensor mean geodesic distances.

The library uses PyTorch (CPU only, already installed).