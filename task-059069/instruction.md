Experimental biomechanical data from a bipedal walking study (1 subject, 2 conditions, 2 runs each) is stored in `/app/data/` as HDF5 files. A protocol configuration database at `/app/protocol/config.db` (SQLite) defines required performance indicators, sensor calibration, output schema, and naming conventions. An output format validator is at `/app/tools/validate_output.py`. HDF5 inspection tools (`h5ls`, `h5dump`) and `sqlite3` are available.

Create an executable entry point at `/app/run_pi` that accepts two positional arguments (`<input_dir> <output_dir>`) and computes gait stability performance indicators from the experimental data. Each HDF5 file contains hierarchically organized sensor channels with metadata stored as dataset attributes (including measurement units). The protocol database contains all information needed to correctly interpret raw sensor readings and understand expected outputs — explore its tables thoroughly.

Subject anthropometric info (mass, height, leg_length) is in a per-subject YAML file in the data directory.

## Output files

All output goes into `<output_dir>`. File naming conventions are defined in the protocol database:

**Per-run files** (4 runs total: conditions 01-02 x runs 01-02):
- `subject_01_cond_{CC}_run_{RR}_spatiotemporal.yaml` — spatiotemporal gait parameters
- `subject_01_cond_{CC}_run_{RR}_stability.yaml` — dynamic stability margins

**Per-condition files** (2 conditions):
- `subject_01_cond_{CC}_aggregated.yaml` — cross-run aggregation of spatiotemporal and stability metrics

**Summary**:
- `summary.csv` — one row per run (header + at least 4 data rows), with columns as defined in the protocol database

## YAML metric schema

Every metric in the per-run and aggregated YAML files must be a dict with three keys:

```yaml
step_time:
  mean: 0.52
  std: 0.03
  unit: "s"
```

## Required metrics

**Spatiotemporal** (in each `_spatiotemporal.yaml`):
`step_time` (s), `stride_time` (s), `step_length` (m), `step_width` (m), `cadence` (steps/min), `walking_speed` (m/s), `stance_ratio` (fraction)

**Stability** (in each `_stability.yaml`):
`mos_ml` (m), `mos_ap` (m). At least one additional field with "xcom" in its name must be present.

## Validation

Invoke the pipeline as: `/app/run_pi /app/data /app/output`

Confirm structural compliance by running: `python3 /app/tools/validate_output.py /app/data /app/output` (must exit with code 0)

The computed metrics must be biomechanically valid for the two walking conditions present in the data (normal speed and fast speed).