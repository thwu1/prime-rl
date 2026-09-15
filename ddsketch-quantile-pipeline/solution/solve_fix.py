#!/usr/bin/env python3
"""
Diagnose and fix bugs in the latency metrics pipeline.

Analysis approach:
1. Read each pipeline module to understand the data flow
2. Identify bugs by checking correctness of core operations
3. Apply fixes and run the pipeline
"""
import subprocess
import sys

# --- Fix 1: aggregator.py ---
# The merge function uses max() for overlapping bucket keys when combining
# sketches from different hosts. This is wrong: each host sketch represents
# independent observations, so their per-bucket counts must be SUMMED to get
# the correct total count per bucket. Using max() discards most of the data,
# causing the merged sketch's bucket counts to sum to roughly 1/N of the
# true total (where N is the number of hosts). Since the sketch's .count
# field is correctly summed, the quantile function tries to reach a rank
# based on the full count but the buckets only contain a fraction of the
# values, causing all quantiles to fall through to max_val.
with open('/app/pipeline/aggregator.py') as f:
    agg_code = f.read()

agg_code = agg_code.replace(
    'target.store[key] = max(target.store[key], cnt)',
    'target.store[key] = target.store[key] + cnt'
)
with open('/app/pipeline/aggregator.py', 'w') as f:
    f.write(agg_code)
print("Fixed aggregator.py: merge now sums bucket counts instead of taking max")

# --- Fix 2: sketch_engine.py ---
# The CollapsingQuantileSketch._collapse() method removes the HIGHEST-key
# buckets (keys[-1], keys[-2]) instead of the LOWEST-key buckets. This
# destroys resolution at the high end of the distribution, which is exactly
# where p95/p99 quantiles need precision. The correct approach is to collapse
# from the bottom (lowest keys), sacrificing resolution for low quantiles
# (which are less critical in latency monitoring) while preserving tail
# accuracy.
with open('/app/pipeline/sketch_engine.py') as f:
    sketch_code = f.read()

sketch_code = sketch_code.replace(
    '            hi_key = keys[-1]\n            next_key = keys[-2]\n            self.store[next_key] += self.store[hi_key]\n            del self.store[hi_key]',
    '            lo_key = keys[0]\n            next_key = keys[1]\n            self.store[next_key] += self.store[lo_key]\n            del self.store[lo_key]'
)
with open('/app/pipeline/sketch_engine.py', 'w') as f:
    f.write(sketch_code)
print("Fixed sketch_engine.py: collapse now removes lowest-key buckets")

# --- Fix 3: reporter.py ---
# The anomaly detection computes abs(current - previous) which is an absolute
# millisecond difference, not a relative change. The threshold (0.5) is meant
# to represent a 50% relative change. Using absolute difference means that
# normal random variation between consecutive windows (a few ms) exceeds the
# 0.5 threshold, creating false positives everywhere. The fix divides by the
# previous value to get the relative (fractional) change.
with open('/app/pipeline/reporter.py') as f:
    rep_code = f.read()

rep_code = rep_code.replace(
    'change = abs(current - previous)',
    'change = abs(current - previous) / previous if previous > 0 else 0.0'
)
with open('/app/pipeline/reporter.py', 'w') as f:
    f.write(rep_code)
print("Fixed reporter.py: anomaly detection now uses relative change")

# --- Run the fixed pipeline ---
print("\nRunning fixed pipeline...")
result = subprocess.run(
    [sys.executable, '/app/pipeline/run_pipeline.py'],
    capture_output=True, text=True
)
print(result.stdout)
if result.returncode != 0:
    print("STDERR:", result.stderr)
    sys.exit(1)
print("Pipeline completed successfully.")
