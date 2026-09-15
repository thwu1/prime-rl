#!/bin/bash

cd /app
python3 /solution/solve_pipeline.py

# Create SQL view for Pareto frontier using sqlite3 CLI
sqlite3 /app/output/benchmark.db "CREATE VIEW IF NOT EXISTS pareto_frontier AS SELECT b1.alpha, b1.max_buckets, b1.p99_max_relative_error, b1.memory_buckets, b1.max_relative_error, b1.mean_relative_error FROM benchmark b1 WHERE NOT EXISTS (SELECT 1 FROM benchmark b2 WHERE b2.p99_max_relative_error <= b1.p99_max_relative_error AND b2.memory_buckets <= b1.memory_buckets AND (b2.p99_max_relative_error < b1.p99_max_relative_error OR b2.memory_buckets < b1.memory_buckets));"

# Generate formatted benchmark report using sqlite3 CLI
echo "=== Benchmark Summary ===" > /app/output/benchmark_report.txt
sqlite3 -column -header /app/output/benchmark.db "SELECT * FROM benchmark ORDER BY alpha, max_buckets;" >> /app/output/benchmark_report.txt
echo "" >> /app/output/benchmark_report.txt
echo "=== Pareto Frontier ===" >> /app/output/benchmark_report.txt
sqlite3 -column -header /app/output/benchmark.db "SELECT * FROM pareto_frontier ORDER BY memory_buckets, p99_max_relative_error;" >> /app/output/benchmark_report.txt
