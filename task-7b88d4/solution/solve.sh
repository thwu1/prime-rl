#!/bin/bash

cd /app
cp /app/perf_takehome.py /app/perf_takehome.py.bak
cp /solution/optimized_kernel.py /app/perf_takehome.py

echo "=== Solution applied. Profiling baseline vs optimized ==="

# Generate the profile report using the vliw_profiler tool
python3 /app/vliw_profiler.py report -o /app/profile_report.json

echo ""
echo "=== Running validation ==="
python3 /app/run_tests.py
