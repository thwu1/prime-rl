Build an evaluation pipeline at `/app/pipeline.py` that performs end-to-end analysis of an HLS code-generation benchmark suite and writes a JSON report to `/app/output/report.json`.

## Environment

The directory `/app/` contains:

- `benchmarks/` — Five HLS kernel benchmarks (`add_arrays`, `dot_product`, `find_max`, `prefix_sum`, `hamming_dist`), each with `reference.cpp`, `testbench.cpp`, and a `candidates/` directory with 10 candidate implementations.
- `dse_config.json` — Design-space exploration parameters and dependency constraints.
- `ppa_analysis/design_points.json` — Hardware design points with area, timing, and power measurements.
- `ppa_analysis/ppa_comparison.json` — Per-benchmark reference vs. generated PPA data.
- `evaluation_spec.json` — Report schema and section definitions.

## Output

The report at `/app/output/report.json` must conform to the schema in `evaluation_spec.json`, covering compilation verification, functional simulation, constrained design-space enumeration, Pass@k evaluation, Pareto frontier identification, and PPA normalization across the benchmark suite.