The permafrost analysis pipeline at `/app/pipeline.py` is non-functional. The pipeline reads site parameters from `/app/config.toml`, computes soil thermal properties via a Fortran shared library (source at `/app/thermal_lib/thermal.f90`, built via `/app/thermal_lib/Makefile`), and implements analytical permafrost models. Results are written to `/app/output.json`.

Running `python3 /app/pipeline.py` currently fails because the build system does not produce the expected shared library (`/app/thermal_lib/libthermal.so`). Even after resolving the build, the pipeline produces numerically incorrect results from errors in both the compiled Fortran thermal property routines and the Python analytical model code.

Reference implementations demonstrating the correct geophysical formulations are at `/app/reference/`. They depend on numpy (not installed) and cannot be executed directly. Soil thermal parameter data is at `/app/data/thermal_parameters.csv`.

Fix all issues across the build system, Fortran source, and Python code so that `python3 /app/pipeline.py` produces correct output.

**Output schema** (`/app/output.json`):

A JSON object keyed by site name (matching `[sites.*]` in the config). Each site value contains:

| Key | Type | Constraint |
|-----|------|------------|
| `air_frost_number` | float | in [0, 1] |
| `ground_surface_temperature` | float | deg C |
| `ground_surface_amplitude` | float | deg C; positive |
| `has_permafrost` | bool | |
| `permafrost_temperature` | float or null | deg C; null when no permafrost |
| `active_layer_thickness` | float or null | meters; null when no permafrost |

**Constraints:**

- Every site in the config must appear in output.
- When `has_permafrost` is `false`, both `permafrost_temperature` and `active_layer_thickness` must be `null`.
- Frozen-ground conductivity asymmetry causes permafrost temperature to be colder than mean ground surface temperature.
- Zero snow depth means ground surface temperature equals air temperature.
- Snow insulation warms the ground surface and reduces temperature amplitude.
