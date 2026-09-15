A simulation framework in `/app/` models a network interface with multiple hardware transmit queues sharing a single global bandwidth limit. Traffic flows with configurable weights and optional demand caps are distributed across queues. The scheduling engine at `/app/scheduler.py` contains only stubs.

Read the framework code (`/app/main.py`, `/app/traffic.py`, `/app/metrics.py`, `/app/scheduler.py`, and scenario files in `/app/scenarios/`) to understand all required interfaces, data flow, and expected behavior.

## Deliverables

**1. Scheduler** — Implement all stubs in `/app/scheduler.py` so the system achieves weighted fair bandwidth allocation across flows regardless of queue assignment. The six scenarios below define the acceptance criteria; all must pass within the listed tolerances.

**2. tc Configuration** — Write an executable script `/app/tc_config.sh` that configures traffic shaping on a dummy interface named `mqsim0` to reflect the `weighted` scenario's allocation policy (80 Mbps global, weights 1/3/2/2). Use `ip` and `tc` commands.

**3. Aggregated Report** — Write an executable script `/app/aggregate.sh` that uses `jq` to merge per-scenario JSON results from `/app/results/` into `/app/results/summary.json` with schema:

```json
{"<scenario_name>": {"jfi": <float>, "utilization": <float>, "num_flows": <int>, "total_throughput_bps": <float>}}
```

## Scenarios

Run via `python3 /app/main.py /app/scenarios/<name>.json /app/results/<name>.json`. All six must pass:

| Scenario | Key constraints |
|---|---|
| `uniform` | 8 equal flows, 4 queues, 100 Mbps — JFI ≥ 0.99, utilization ≥ 0.98 |
| `skewed` | 10 equal flows, 1/2/3/4 per queue, 100 Mbps — JFI ≥ 0.99, utilization ≥ 0.98 |
| `weighted` | weights 1,3,2,2 across 2 queues, 80 Mbps — JFI ≥ 0.99, throughput ratio (w3÷w1) in [2.8, 3.2] |
| `demand_limited` | 4 equal flows, flow 0 capped 10 Mbps, 100 Mbps — cap ≤ 11 Mbps, uncapped ≥ 28 Mbps each, utilization ≥ 0.98 |
| `dynamic` | 4 initial + 2 at t=1s, 3s duration, 100 Mbps — utilization ≥ 0.95, originals max/min < 1.05, late pair diff < 5%, full-duration/late byte ratio in [1.6, 1.9] |
| `cascade` | 5 flows (weights 1,1,2,1,1; caps 5/15/25/∞/∞ Mbps), 3 queues, 100 Mbps — each cap within 1 Mbps, uncapped ≥ 26 Mbps each, utilization ≥ 0.98 |

Per-scenario output JSON: `{"throughputs": {"<id>": <bytes/s>}, "jains_fairness_index": <float>, "utilization": <float>, "total_throughput_bytes_per_sec": <float>, "global_rate_bytes_per_sec": <float>}`. All results in `/app/results/`.