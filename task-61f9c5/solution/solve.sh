#!/bin/bash

set -e

# Step 1: Deploy the controller implementation
cp /solution/controller.py /app/controller.py

# Step 2: Run the simulation framework across all scenarios
python3 /app/framework.py

# Step 3: Generate convergence plot with gnuplot
gnuplot /solution/convergence.gp
echo "Generated /app/output/convergence.png"

# Step 4: Generate summary report with jq
jq -n \
  --slurpfile sym /app/output/symmetric_metrics.json \
  --slurpfile bur /app/output/bursty_metrics.json \
  --slurpfile asym /app/output/asymmetric_metrics.json \
  '{
    symmetric: {
      avg_tail_dirty_ratio: $sym[0].avg_tail_dirty_ratio,
      max_pause_ms: $sym[0].max_pause_ms,
      avg_tail_throughput: $sym[0].avg_tail_throughput
    },
    bursty: {
      avg_tail_dirty_ratio: $bur[0].avg_tail_dirty_ratio,
      max_pause_ms: $bur[0].max_pause_ms,
      avg_tail_throughput: $bur[0].avg_tail_throughput
    },
    asymmetric: {
      avg_tail_dirty_ratio: $asym[0].avg_tail_dirty_ratio,
      max_pause_ms: $asym[0].max_pause_ms,
      avg_tail_throughput: $asym[0].avg_tail_throughput
    }
  }' > /app/output/summary.json

echo "Generated /app/output/summary.json"
echo "Done."
