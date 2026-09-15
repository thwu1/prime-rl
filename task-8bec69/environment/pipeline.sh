#!/bin/bash
# SGLang monitoring pipeline — runs all stages
set -e

echo "=== Stage 1: Validate Prometheus recording rules ==="
promtool check rules /app/rules/sglang_slos.yml

echo "=== Stage 2: Convert .prom scrapes to JSON snapshots ==="
python3 /app/prom_to_json.py

echo "=== Stage 3: Compute interval deltas via jq ==="
bash /app/compute_intervals.sh

echo "=== Stage 4: Run SLO analyzer ==="
python3 /app/analyze.py

echo "=== Pipeline complete ==="
