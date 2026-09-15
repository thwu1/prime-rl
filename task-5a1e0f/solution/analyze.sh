#!/bin/bash
# Analysis pipeline: EDN parsing -> linearizability checking -> visualization

set -e
cd /app

# Clean intermediate state
rm -rf /tmp/json_histories
mkdir -p /app/viz /tmp/json_histories

# Step 1: Convert EDN histories to JSON using babashka
bb /app/edn_to_json.bb /app/histories /tmp/json_histories

# Step 2: Run linearizability checker on JSON histories
python3 /app/linearizability_checker.py /tmp/json_histories /app/results.json

# Step 3: Generate Graphviz DOT/SVG visualizations for non-linearizable histories
python3 /app/viz_generator.py /app/results.json /tmp/json_histories /app/viz
