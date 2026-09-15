#!/usr/bin/env bash

# Deploy the metrics engine solution
cp /solution/metrics_engine_solution.py /app/metrics_engine.py
chmod +x /app/metrics_engine.py

# Verify the solution works by running all subcommands

# 1. Generate limits from the GCD reference run
python3 /app/metrics_engine.py generate-limits \
    /app/runs/gcd_nangate45.metrics.json \
    -o /tmp/verify_gcd_limits.json
echo "generate-limits: exit $?"

# 2. Self-check should pass (exit 0)
python3 /app/metrics_engine.py check \
    /app/runs/gcd_nangate45.metrics.json \
    /tmp/verify_gcd_limits.json > /tmp/verify_check_pass.json
echo "self-check: exit $?"

# 3. Degraded check should fail (exit 1)
python3 /app/metrics_engine.py check \
    /app/runs/gcd_nangate45_degraded.metrics.json \
    /tmp/verify_gcd_limits.json > /tmp/verify_check_fail.json || true
echo "degraded-check: exit $? (expected non-zero)"

# 4. Margin report
python3 /app/metrics_engine.py margin-report \
    /app/runs/gcd_nangate45.metrics.json \
    /tmp/verify_gcd_limits.json > /tmp/verify_margin.json
echo "margin-report: exit $?"

# 5. Compare runs
python3 /app/metrics_engine.py compare \
    /app/runs/gcd_nangate45.metrics.json \
    /app/runs/gcd_nangate45_degraded.metrics.json > /tmp/verify_compare.json
echo "compare: exit $?"

echo "Solution deployed and verified."
