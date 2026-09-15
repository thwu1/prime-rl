#!/bin/bash
set -e

echo "=== Fuzzer Evaluation Pipeline ==="

# Stage 1: Extract configuration from experiment database
echo "[1/3] Extracting configuration..."
/app/tools/extract_config.sh > /tmp/pipeline_config.json

# Stage 2: Run core analysis
echo "[2/3] Running analysis..."
cd /app
python3 /app/tools/analysis.py

# Stage 3: Post-process aggregate ranking
echo "[3/3] Post-processing output..."
jq -f /app/tools/format_ranking.jq /app/output/aggregate_ranking.json > /tmp/ranking_tmp.json
mv /tmp/ranking_tmp.json /app/output/aggregate_ranking.json

echo "=== Pipeline complete ==="
