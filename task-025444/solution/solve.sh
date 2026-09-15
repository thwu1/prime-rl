#!/bin/bash

pip3 install pyyaml==6.0.2 -q

# Step 1: Fix all 6 pipeline bugs
python3 /solution/fix_pipeline.py

# Step 2: Run the fixed pipeline (produces scorecard.json, benchmark.db, audit.csv)
bash /app/run_pipeline.sh

# Step 3: Fix the jq report template and generate summary_report.json
python3 /solution/fix_jq_report.py

# Step 4: Generate forensic evaluation comparing reference vs correct scorecard
python3 /solution/generate_evaluation.py
