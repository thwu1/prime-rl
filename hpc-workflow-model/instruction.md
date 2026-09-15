Five candidate HPC systems were benchmarked for a national laboratory procurement. Raw execution logs are at `/data/benchmark_data/` (one subdirectory per system). System specs are at `/data/system_specs.json`, workload definitions at `/data/workload_specs.json`, and procurement constraints at `/data/procurement_requirements.json`.

The logs come from different vendor teams in heterogeneous formats with data quality issues (unit mismatches, error entries, duplicates, missing benchmarks). These must be detected and handled before analysis.

Produce `/app/results/evaluation.json` conforming to the output specification in the procurement requirements. It must contain: cleaned performance summaries, speedup ratios against the reference system, weighted composite scores, constraint-based feasibility assessment, Pareto-optimal candidate identification, cost-efficiency ranking, and a final recommendation.

All floating-point values must be accurate to at least 3 significant figures.