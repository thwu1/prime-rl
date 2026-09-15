A KTransformers CPU/GPU heterogeneous MoE inference deployment at `/app/` is crashing at startup and, based on prior runs, exhibits suboptimal throughput. The deployment environment contains hardware specification files, model configuration with quantization parameters, workload profiling data, the current launch configuration, and server error logs spread across subdirectories under `/app/`.

Analyze the full deployment environment and produce `/app/audit_report.json` conforming to the schema defined in `/app/expected_schema.json`. The report must:

- Accurately characterize the hardware platform's CPU capabilities, topology, and accelerator inventory by examining the system specification files.
- Compute the GPU memory budget available for MoE expert placement given the model's quantization format and the measured non-expert VRAM consumption.
- Identify all configuration errors in the current launch setup — the OOM crash visible in the logs is not the only problem.
- Determine the expert-to-GPU assignment that maximizes the share of profiled workload activations served from GPU memory, given the computed expert budget.