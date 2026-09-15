A GPU inference analysis system is partially set up at `/app/`. It includes:

- A C shared library (`/app/roofline_core.c` → `/app/libroofline.so`) for roofline model computations, with a Python ctypes wrapper at `/app/roofline.py`
- A SQLite database at `/app/data/hardware.db` with specifications for 4 NVIDIA GPUs (query with `sqlite3`)
- Workload scenarios at `/app/data/scenarios.json` covering decode and prefill phases with MHA, GQA, and MQA attention
- Analysis parameters at `/app/data/analysis.json`
- Partial reference values at `/app/data/reference.json`
- Required output schema at `/app/data/output_schema.json`

The C library contains bugs that produce incorrect roofline predictions. No attention analysis or multi-GPU evaluation code exists.

Design and implement an engine that evaluates each attention workload across all GPUs and produces an optimal placement report at `/app/report.json`:

- Model attention FLOPs and HBM memory accesses correctly for all variants, counting each fused multiply-add as 2 FLOPs and using KV-head counts (not query-head counts) for key/value memory terms
- For each workload, evaluate achievable throughput on every GPU via roofline analysis, check whether the workload's KV cache fits within GPU HBM, and select the optimal GPU (highest throughput among feasible GPUs; ties broken by peak TFLOPS descending, then name ascending)
- Compute per-GPU critical prefill sequence lengths and per-group-size arithmetic intensities as specified in the analysis parameters
- The report must conform to the schema at `/app/data/output_schema.json`