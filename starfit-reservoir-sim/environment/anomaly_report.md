# Cascade Simulation Diagnostic Report

## Status

The cascade simulation at `/app/` is non-functional. Running `python3 /app/run_cascade.py` fails at multiple stages.

## Phase 1: Data Loading Failure

The simulation fails immediately during parameter loading from `/app/data/cascade.nc`:

```
KeyError: 'reach_K_days'
```

The NetCDF input file appears to have been produced by an upstream pipeline whose variable naming convention diverges from what the simulation code expects. The data loading module at `/app/reservoir/io_utils.py` defines the expected schema. Use `ncdump -h /app/data/cascade.nc` to inspect the actual file structure and identify all discrepancies between the file's contents and the expected variable names and global attributes.

## Phase 2: Missing Implementations

After resolving data loading issues, the cascade-level modules (`routing.py`, `cascade.py`, `metrics.py`) raise `NotImplementedError`. These must be implemented according to `/app/specification.md`.

## Phase 3: Physical Constraint Violations

Once missing modules are implemented, validation against physical constraints reveals anomalies in the base reservoir simulation modules:

- **NOR envelope anomaly**: The lower NOR bound's seasonal oscillation appears phase-shifted by approximately π/2 radians relative to the upper bound. Both bounds should follow identical sinusoidal functional forms (per the specification), but the lower bound's peak storage targets occur approximately 13 weeks offset from expected timing. The upper bound appears correct.

- **Release magnitude anomaly**: The STARFIT release function produces systematically elevated release rates — approximately 1× mean annual flow too high across all availability levels and seasons. The bias is proportional to mean flow and persists regardless of storage state, suggesting an error in how inflow is standardized rather than in the seasonal or availability components.

- **Mass conservation failure**: Under low-flow conditions when storage approaches zero, the negative-storage protection mechanism introduces cumulative mass balance violations. Total outflow slightly exceeds total inflow plus storage change. The error is small per timestep but accumulates over multi-year simulations, indicating that the protection adjusts storage without correspondingly adjusting the recorded release rate.

## Context

The system models three reservoirs connected by Muskingum-routed channels. Correct operation requires strict mass conservation at each reservoir and system-wide, proper seasonal operating envelopes, and physically valid release rates derived from the STARFIT framework.
