#!/bin/bash

cd /app

# Replace the buggy DDSketch implementation with the corrected version
cp /solution/corrected_sketch.py /app/sketch.py

# Verify the corrected sketch loads without errors
python3 -c "
import sys
sys.path.insert(0, '/app')
from sketch import DDSketch
s = DDSketch(alpha=0.01)
for v in [1.0, 2.0, 5.0, 10.0]:
    s.add(v)
assert s.count == 4
assert s.min_value == 1.0
assert s.max_value == 10.0
p50 = s.quantile(0.5)
assert 1.0 <= p50 <= 10.0, f'Bad p50: {p50}'
print('Corrected sketch verified OK')
"

# Analyze per-tier data distributions using sqlite3
echo "=== Per-tier data distribution analysis ==="
sqlite3 -header -column /app/data/metrics.db \
  "SELECT service_tier, COUNT(*) as n, MIN(latency_ms) as min_val, MAX(latency_ms) as max_val, AVG(latency_ms) as avg_val FROM latency_samples GROUP BY service_tier ORDER BY service_tier;"

# Compute optimal per-tier configurations based on data analysis and SLA constraints
python3 /solution/compute_config.py

# Run the pipeline with the optimized configuration
python3 /app/pipeline.py

echo "=== Pipeline complete ==="
