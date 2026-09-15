`/app/data/` contains three ADIOS2 BP5 sensor datasets from a fluid dynamics experiment, each with different spatial resolution, temporal sampling rate, and variable schema. `/app/SPEC.md` defines the required output format.

Produce:

1. `/app/fused.bp` — A unified BP5 dataset integrating all sensor fields onto the velocity sensor's grid and timebase, conforming to SPEC.md.

2. `/app/results/fusion_report.json` — Per-step diagnostics and data quality assessment, conforming to the schema in SPEC.md.

Sensor metadata attributes contain relevant calibration parameters.