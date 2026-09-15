#!/bin/bash
set -e

mkdir -p /app/pipeline/tmp

echo "Stage 1: Extracting data from database..."
sqlite3 /app/experiment/fuzzbench.db < /app/pipeline/extract_data.sql

echo "Stage 2: Running statistical tests (R)..."
Rscript /app/pipeline/statistical_tests.R

echo "Stage 3: Computing effect sizes and scores (Python)..."
python3 /app/pipeline/compute_metrics.py

echo "Stage 4: Assembling results (jq)..."
jq -n \
    --slurpfile stats /app/pipeline/tmp/stats_output.json \
    --slurpfile metrics /app/pipeline/tmp/metrics_output.json \
    -f /app/pipeline/merge_results.jq > /app/results.json

echo "Analysis complete. Results written to /app/results.json"
