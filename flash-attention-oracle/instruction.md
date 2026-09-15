You are planning a Flash Attention deployment across a heterogeneous GPU cluster. Four data sources describe the environment:

- `/app/cluster.db` — SQLite database. Table `nodes`: name, gpu, compute_cap_major, compute_cap_minor, gpu_memory_gb, cuda_version, cpu_cores, system_memory_gb, nvcc_threads, peak_tflops_fp16, memory_bandwidth_gbps, cost_per_hour_usd.
- `/app/cluster_config.toml` — Per-node target GPU architectures and build system parameters.
- `/app/workloads.csv` — Workloads to deploy.
- `/app/source/` — Flash Attention library source: `setup.py` (build system), `flash_attn_interface.py` (kernel interface), `benchmark_flash_attention.py` (performance measurement).

Analyze the source code to understand how the library builds, configures its kernels, and measures performance. Cross-reference all four data sources to produce `/app/report.json`:

```json
{
  "nodes": {
    "<node_name>": {
      "gencode_flags": ["<str>", ...],
      "max_build_jobs": <int>,
      "estimated_build_time_minutes": <float>,
      "workloads": {
        "<workload_name>": {
          "kernel_block_n": <int>,
          "fwd_flops": <int>,
          "memory_per_layer": {"standard_bytes": <int>, "flash_bytes": <int>},
          "max_batch_flash": <int>,
          "feasible": <bool>,
          "data_parallel_gpus": <int>,
          "price_performance": <float>
        }
      }
    }
  },
  "performance_analysis": {
    "<workload_name>": {"memory_savings_ratio": <float>},
    "flash_attention_impact": ["<workload_name>", ...]
  },
  "build_priority": ["<node_name>", ...],
  "deployment_plan": {
    "<workload_name>": {"assigned_node": "<str>", "gpus_required": <int>, "price_performance": <float>}
  },
  "ranking": ["<node_name>", ...]
}
```

Field descriptions:
- `gencode_flags`: NVCC `-gencode` arguments the build system would emit for this node's CUDA version and architecture targets. Each flag and its value are separate elements.
- `max_build_jobs`: Build parallelism the build system auto-detects for this node's hardware resources.
- `estimated_build_time_minutes`: Compilation duration estimate using the node's parallelism and build configuration. Round to 1 decimal.
- `kernel_block_n`: Tile size the attention kernel selects for this GPU and workload.
- `fwd_flops`: Forward-pass floating-point operations for this workload.
- `memory_per_layer`: Single-layer memory under two attention models. `standard_bytes`: Q/K/V/output tensors plus full materialized score matrix. `flash_bytes`: Q/K/V/output tensors plus logsumexp statistics.
- `max_batch_flash`: Largest integer batch fitting in GPU memory under the flash model.
- `feasible`: True if the workload batch fits on one GPU.
- `data_parallel_gpus`: 1 if feasible; otherwise, GPUs needed to cover the batch.
- `price_performance`: Cost-efficiency in TFLOPS per dollar-hour, accounting for multi-GPU cost. Round to 2 decimals.
- `memory_savings_ratio`: How many times more memory standard attention uses versus flash for this workload. Round to 1 decimal.
- `flash_attention_impact`: Workloads ranked by memory savings, greatest benefit first.
- `build_priority`: Nodes by build speed, fastest first. Alphabetical tiebreak.
- `deployment_plan`: Most cost-effective single-GPU-feasible node per workload. When no single-GPU option exists: fewest GPUs, then cost-efficiency, then alphabetical.
- `ranking`: Nodes by average price-performance across all workloads, best first. Alphabetical tiebreak.