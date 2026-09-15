#!/bin/bash

pip3 install numpy==2.1.3 -q

# Step 1: Analyze pipeline error logs with jq
echo "=== Pipeline Error Log Analysis ==="
jq -s '
  [.[] | select(.status? == "FAIL")] |
  group_by(.func) |
  map({
    func: .[0].func,
    backend: .[0].backend,
    failure_count: length,
    categories: [.[].category] | unique
  })
' /app/logs/pipeline_errors.ndjson

echo ""
echo "=== Chain Summaries ==="
jq -s '[.[] | select(.type? == "chain_summary")]' /app/logs/pipeline_errors.ndjson

# Step 2: Run benchmarks for all three libraries
echo ""
echo "=== Running Benchmarks ==="
python3 /app/run_benchmark.py alpha
python3 /app/run_benchmark.py beta
python3 /app/run_benchmark.py gamma

# Step 3: Analyze benchmark results with sqlite3
echo ""
echo "=== Benchmark Analysis ==="
sqlite3 /app/rotations.db "
WITH error_summary AS (
    SELECT library, func,
           MAX(error) AS max_err,
           AVG(error) AS avg_err,
           COUNT(*) AS n_tests
    FROM benchmark_results
    GROUP BY library, func
),
classified AS (
    SELECT func, library, max_err,
           CASE WHEN max_err < 1e-6 THEN 'CORRECT' ELSE 'FLAWED' END AS status
    FROM error_summary
)
SELECT func, library, status, printf('%.2e', max_err) AS max_error
FROM classified
ORDER BY func, library;
"

echo ""
echo "=== Category Breakdown for Flawed Functions ==="
sqlite3 /app/rotations.db "
SELECT library, func, category, printf('%.4e', MAX(error)) AS max_err
FROM benchmark_results
WHERE error >= 1e-6
GROUP BY library, func, category
ORDER BY func, library, category;
"

# Step 4: Generate all deliverables
echo ""
echo "=== Generating Deliverables ==="
python3 /solution/solve_audit.py
