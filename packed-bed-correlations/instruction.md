The packed-bed reactor analysis pipeline at `/app/` produces incorrect numerical results. The build is orchestrated by `/app/Makefile`; running `make` in `/app/` compiles a C shared library (`libcorr.so`) from `/app/correlations/native_impl.c` and then executes the Python entry point `pipeline.py`.

The pipeline reads scenario parameters from `/app/scenarios.toml`, computes pressure drops through thirteen correlation functions — eleven in Python under `/app/correlations/`, two in compiled C loaded via `ctypes` through `/app/correlations/native.py` — determines minimum fluidization velocities in `/app/fluidization.py`, and calculates terminal settling velocities in `/app/settling.py`.

Results are stored in `/app/results.db` (SQLite 3) with tables:

```
pressure_drops(scenario TEXT, correlation TEXT, value REAL)
fluidization(scenario TEXT, correlation TEXT, vmf REAL)
terminal_velocity(scenario TEXT, vt REAL)
```

Primary keys: `(scenario, correlation)` for `pressure_drops` and `fluidization`; `(scenario)` for `terminal_velocity`.

Each of the four scenarios must have entries for all 13 correlations in both `pressure_drops` and `fluidization`, plus one row in `terminal_velocity`. Scenarios with a tube diameter (`Dt`) must have wall-effect corrections applied consistently across all computations.

Debug and correct all numerical errors in both the Python modules and the C source so output values match reference computations within 0.1% relative tolerance. Rebuild the shared library and re-run the pipeline after corrections.

The `fluids` Python package must not be imported by any code under `/app/`.
