Rigid-body simulation recordings in HDF5 format are in `/app/data/` (see `/app/data/FORMAT.md` for the data schema). Each captures frame-by-frame state — positions, quaternion orientations, linear and angular velocities — of one or more rigid bodies evolving under specified physical conditions. Bodies may be spheres or ellipsoids; ellipsoid inertia tensors are given in the body's principal-axis frame.

Validation parameters and output paths are in `/app/config.toml`.

Create `/app/validator.py` so that `python3 /app/validator.py` analyses every `.h5` trajectory in `/app/data/` and produces:

1. **Per-scenario JSON reports** in the configured reports directory as `<stem>_report.json`:

```json
{
  "plausibility_score": <float 0–100>,
  "anomalies": {
    "energy_violations": [{"frame": <int>, ...}, ...],
    "momentum_violations": [{"frame": <int>, ...}, ...],
    "interpenetrations": [{"frame": <int>, "bodies": [<str>, <str>], ...}, ...],
    "kinematic_violations": [{"frame": <int>, ...}, ...],
    "angular_momentum_violations": [{"frame": <int>, ...}, ...],
    "jitter_detected": <bool>
  }
}
```

2. **A SQLite database** at the configured path:

```sql
CREATE TABLE scenarios (name TEXT PRIMARY KEY, plausibility_score REAL, total_anomalies INTEGER);
CREATE TABLE anomalies (id INTEGER PRIMARY KEY AUTOINCREMENT, scenario_name TEXT REFERENCES scenarios(name), anomaly_type TEXT, frame INTEGER, details TEXT);
```

3. **Phase-space diagnostic plots** — for each scenario and body, a PNG in the configured plots directory as `<stem>_<body_name>.png`, produced with `gnuplot`. Show position vs. velocity for the axis of dominant motion.

Physically consistent trajectories must score ≥ 85; anomalous ones substantially lower, penalised per the scoring weights in the config.