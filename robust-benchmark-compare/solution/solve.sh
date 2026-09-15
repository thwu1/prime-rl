#!/usr/bin/env bash

cp /solution/benchmark_compare_solution.py /app/benchmark_compare.py
python3 /app/benchmark_compare.py /data/run_a.json /data/run_b.json /app/report.json
echo "Solution applied and report generated at /app/report.json"
