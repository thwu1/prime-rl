#!/bin/bash

cd /opt/ga_bench

echo "=== Benchmarking existing strategies ==="
python3 /opt/ga_bench/run_benchmark.py

echo ""
echo "=== Implementing UnifiedNormalizer ==="
python3 /solution/implement_unified.py

echo ""
echo "=== Generating evaluation report ==="
python3 /solution/generate_report.py

echo ""
echo "=== Verifying unified strategy ==="
python3 /opt/ga_bench/run_benchmark.py
