A CUDA SGEMM warptiling kernel is implemented in `/app/src/kernel_warptiling.cuh` with launch configuration and constraints in `/app/src/runner.cu`. Compiler output from building five configurations with `nvcc --ptxas-options=-v` is in `/app/build_output.log`. GPU hardware specifications are in `/app/gpu.json`. The parameter search space is defined in `/app/search_ranges.json`.

Produce:

1. A SQLite database at `/app/output/autotune.db` conforming exactly to the schema in `/app/db_schema.sql`. The `configurations` table must contain every valid parameter combination with correctly computed occupancy metrics. The `bottlenecks` table must identify which hardware resource(s) limit the resident block count for each configuration. Create the `idx_configs_occupancy` index and implement the `occupancy_histogram` and `bottleneck_distribution` views as specified in the schema.

2. A JSON file at `/app/output/analysis.json` following the format in `/app/output_schema.json`, including aggregate statistics across all valid configurations and analysis of the four query configurations defined there.

You must derive a register usage model for arbitrary parameter combinations by analyzing the kernel source code structure and calibrating against the five compiler-profiled builds. You must extract all kernel launch constraints from `runner.cu`, enumerate valid parameter combinations from the search space, and compute theoretical SM occupancy for each using the GPU's hardware resource allocation model.