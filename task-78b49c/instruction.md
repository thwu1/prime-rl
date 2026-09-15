During a fleet-wide GPU driver update, kernel launch telemetry was collected from internal benchmarks running across five anonymized GPU models (GPU_A through GPU_E). Some telemetry records contain measurement artifacts from the driver transition period. The hardware inventory has gaps from failed automated discovery during the upgrade window.

## Input

- `/app/data/profiling.db` — SQLite database containing kernel launch profiling records in a normalized schema across three tables (`gpu_sessions`, `kernel_defs`, `launch_records`). Launch records reference GPU sessions and kernel definitions via foreign keys. You will need to query the database with appropriate joins to correlate GPU identities and kernel names with measured SM residency metrics.
- `/app/data/hw_discovery.xml` — nvidia-smi XML discovery output for the fleet. Product names and compute capabilities failed to resolve during the driver transition; known SM resource limits are populated, unknown parameters show `[DISCOVERY FAILED]`. Parse the XML tree to extract each GPU's `internal_label` and available `sm_resource_limits` attributes.
- `/app/data/target_kernels.json` — New kernel workloads needing optimized launch configurations; `shared_mem_per_block` is either a fixed integer or a Python expression string using `block_size` (to be evaluated per candidate block size).
- `/app/data/architectures.yaml` — YAML reference of candidate NVIDIA compute capabilities with generation names, max warp/block limits, and architectural notes. Parse the YAML to extract candidate architecture constraints.
- `/app/data/incident.log` — Timestamped syslog-format diagnostic log from the driver upgrade and telemetry collection.

## Deliverable

Produce `/app/results.json` with this exact structure:

```json
{
    "hardware_parameters": {
        "<gpu_id>": {
            "max_warps_per_sm": "<int>",
            "max_blocks_per_sm": "<int>",
            "total_shared_mem_per_sm": "<int>",
            "shared_mem_alloc_granularity": "<int>",
            "register_alloc_granularity": "<int>"
        }
    },
    "architecture_mapping": {
        "<gpu_id>": "<sm_version from candidate list>"
    },
    "corrupted_row_ids": ["<sorted list of integer record_ids>"],
    "optimal_configs": {
        "<kernel_name>": {
            "<gpu_id>": {
                "optimal_block_size": "<int>",
                "predicted_occupancy": "<float>"
            }
        }
    }
}
```

- `hardware_parameters`: The five unknown architectural parameters for each of the five GPUs, reconstructed from the profiling telemetry
- `architecture_mapping`: Each anonymized GPU mapped to an NVIDIA compute capability from the candidate list in `/app/data/architectures.yaml`
- `corrupted_row_ids`: Telemetry records containing measurement artifacts, identified by their `record_id` from the `launch_records` table, sorted ascending
- `optimal_configs`: For each target kernel on each GPU, the block size (a positive multiple of the GPU's warp size, not exceeding `max_threads_per_block`) that maximizes predicted warp occupancy; among block sizes achieving equal occupancy, report the largest