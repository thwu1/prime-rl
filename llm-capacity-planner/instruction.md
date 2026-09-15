A Mixture-of-Experts language model is deployed on an H100 GPU cluster using SGLang. Load tests at escalating Poisson request rates reveal the system saturating before reaching target throughput. Investigate the benchmark data, model architecture, and server runtime state to produce a capacity planning analysis.

## Data

- `/app/data/benchmarks.db` — SQLite database with per-request traces across multiple request rates. Schema includes `runs` (metadata per rate) and `traces` (per-request latency data; inter-token latency arrays stored as JSON text in the `itl` column)
- `/app/data/server_config.yaml` — YAML deployment configuration with cluster hardware specs, server tuning parameters (including the GPU memory allocation fraction), and benchmark settings
- `/app/data/model_config.json` — MoE transformer architecture specification
- `/app/data/slo_targets.json` — Production latency and throughput SLOs
- `/app/data/server_logs/` — SGLang server startup and per-run scheduler logs

## Deliverable

Write `/app/analysis_results.json` with:

- `trace_analysis`: Per-rate serving performance breakdown from successful requests. Include standard LLM serving latency metrics — TTFT, TPOT, ITL — at p50/p95/p99 in milliseconds, plus output throughput (tok/s). Key entries as `rate_<R>` (e.g. `rate_2.0`). Name fields descriptively: `ttft_p99_ms`, `tpot_p50_ms`, `itl_p99_ms`, `throughput_tok_per_sec`.

- `memory_analysis`: Full architecture memory footprint. Report `model_weights_total_gb` (accounting for every parameter group in the MoE transformer), `kv_cache_bytes_per_token`, and per-TP-degree feasibility under `configurations` (keys `tp_1` through `tp_8`) with `fits`, `max_kv_tokens`, and per-GPU weight size. Derive the usable memory budget from the deployment configuration.

- `saturation_rate`: Maximum tested request rate still meeting the TTFT p99 SLO.

- `recommended_config`: Optimal `tp_size` and `dp_size` for the cluster, with `estimated_throughput_tok_per_sec`, `estimated_ttft_p99_ms`, `estimated_tpot_p99_ms`.