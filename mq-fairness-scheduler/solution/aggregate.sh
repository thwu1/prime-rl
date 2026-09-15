#!/bin/bash
#
# Aggregate per-scenario JSON results into a single summary using jq.

cd /app/results

jq -n '
{
  "uniform": (input | {
    jfi: .jains_fairness_index,
    utilization: .utilization,
    num_flows: (.throughputs | length),
    total_throughput_bps: .total_throughput_bytes_per_sec
  }),
  "skewed": (input | {
    jfi: .jains_fairness_index,
    utilization: .utilization,
    num_flows: (.throughputs | length),
    total_throughput_bps: .total_throughput_bytes_per_sec
  }),
  "weighted": (input | {
    jfi: .jains_fairness_index,
    utilization: .utilization,
    num_flows: (.throughputs | length),
    total_throughput_bps: .total_throughput_bytes_per_sec
  }),
  "demand_limited": (input | {
    jfi: .jains_fairness_index,
    utilization: .utilization,
    num_flows: (.throughputs | length),
    total_throughput_bps: .total_throughput_bytes_per_sec
  }),
  "dynamic": (input | {
    jfi: .jains_fairness_index,
    utilization: .utilization,
    num_flows: (.throughputs | length),
    total_throughput_bps: .total_throughput_bytes_per_sec
  }),
  "cascade": (input | {
    jfi: .jains_fairness_index,
    utilization: .utilization,
    num_flows: (.throughputs | length),
    total_throughput_bps: .total_throughput_bytes_per_sec
  })
}
' uniform.json skewed.json weighted.json demand_limited.json dynamic.json cascade.json > summary.json
