# Reference Implementations

These files are adapted from the **permamodel** Python package
(Jafarov, Wang, Pierce et al.) — a research-grade permafrost
modeling toolkit.

## Files

- `ku_model.py` — Kudryavtsev active-layer model implementing soil
  thermal property calculations, snow/vegetation insulation effects,
  permafrost temperature estimation, and active layer thickness
  computation. Uses numpy array operations.

- `frost_number.py` — Nelson & Outcalt (1983) frost number from
  degree-day freezing/thawing indices. Assumes sinusoidal annual
  temperature cycle.

## Dependencies

These implementations use numpy for numerical operations. They are
provided as a reference for the correct geophysical formulations and
cannot be executed directly if numpy is not installed.

## Architecture

The pipeline at `/app/pipeline.py` uses a compiled Fortran shared
library (`/app/thermal_lib/libthermal.so`) for soil thermal property
calculations (conductivity and heat capacity), called via Python
ctypes. The Fortran library should implement equivalent formulations
to those documented in `ku_model.py`.
