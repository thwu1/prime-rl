The environment at `/app/` contains a partial setup for a cross-language numerical validation pipeline for a PDE solver. `/app/spec.md` contains the full mathematical specification, required Python interfaces, and reference data format definitions. Implement all missing components to complete the pipeline.

## Provided in `/app/`

- `spec.md` — Complete specification (mathematics, interfaces, reference data formats, accuracy thresholds)
- `problem.py` — Python PDE discretization module
- `octave/phifun.m` and `octave/ks_setup.m` — Octave implementations
- `Makefile` — Skeleton with empty targets

GNU Octave is available via `octave --no-gui --silent`.

## Required deliverables in `/app/`

- `octave/gen_reference.m` — Generates reference CSV files in `/app/reference/` as specified in `spec.md`
- `solver.py` — Implements the Python interfaces defined in `spec.md`
- `validate.py` — Loads Octave reference CSVs, computes Python equivalents, exits 0 only if all tolerances from `spec.md` are met
- Completed `Makefile` with working `reference`, `validate`, `all`, and `clean` targets

## Acceptance criteria

- `make all` succeeds end-to-end from a clean state
- All accuracy thresholds defined in `spec.md` are met
- The time integrator achieves the convergence order expected from the scheme
- Solutions are real-valued, finite, and conserve the spatial mean to within 1e-8
- The solver works correctly for different mode counts (e.g., N=32 and N=64)