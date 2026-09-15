#!/bin/bash

cd /app

# Step 1: Convert raw perf script output to folded stack format
/opt/FlameGraph/stackcollapse-perf.pl profiles/baseline.perf > /tmp/baseline_all.folded
/opt/FlameGraph/stackcollapse-perf.pl profiles/regression.perf > /tmp/regression_all.folded

# Step 2: Filter to the target process and strip the process name prefix
grep "^portal-api;" /tmp/baseline_all.folded | sed 's/^portal-api;//' > /tmp/baseline.folded
grep "^portal-api;" /tmp/regression_all.folded | sed 's/^portal-api;//' > /tmp/regression.folded

# Step 3: Run the differential analysis
python3 /solution/analyzer.py /tmp/baseline.folded /tmp/regression.folded
