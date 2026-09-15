Implement the Generalized Moving Peaks Benchmark (GMPB) system and an optimizer that meets the performance thresholds specified in the configuration.

The full mathematical specification is at `/app/spec.md`. Problem instance configurations and performance thresholds are at `/app/config.json`.

Your deliverables:

- `/app/peaks.c` and `/app/Makefile`: C source and build file that produce `/app/libpeaks.so`, as defined in the spec.
- `/app/gmpb.py`: Python GMPB class implementing the complete API defined in the spec. Must produce deterministic, reproducible landscapes for any given seed.
- `/app/optimizer.py`: A `DynamicOptimizer` class that optimizes GMPB instances, achieving offline errors below the per-instance thresholds in `/app/config.json`.
- `/app/run.py`: Runner that optimizes all configured instances and persists results to `/app/results.json` (JSON mapping instance names to dicts containing `offline_error`) and `/app/results.db` (SQLite database with the schema defined in the spec).