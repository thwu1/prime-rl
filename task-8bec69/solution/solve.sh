#!/bin/bash

# Fix all broken pipeline components and implement the analyzer

# Step 1: Fix Prometheus recording rules (PromQL syntax errors)
cp /solution/fixed_rules.yml /app/rules/sglang_slos.yml

# Step 2: Fix jq interval computation (cumulative vs delta, .sum vs .count)
cp /solution/fixed_intervals.sh /app/compute_intervals.sh
chmod +x /app/compute_intervals.sh

# Step 3: Create the SLO burn-rate analyzer from scratch
cp /solution/analyzer.py /app/analyze.py

# Step 4: Run the full pipeline
cd /app && bash /app/pipeline.sh
