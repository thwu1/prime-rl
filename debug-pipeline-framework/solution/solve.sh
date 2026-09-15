#!/bin/bash

# Install dependencies
pip3 install coverage==7.6.1 pytest==8.3.4 -q

# Step 1: Deploy the fault localization tool
cp /solution/fl_tool_impl.py /app/fl_tool.py

# Step 2: Run SBFL + clustering on the buggy code (BEFORE fixing bugs)
# Generates: coverage_matrix.json, fl_results.json, fault_clusters.json
cd /app
python3 /app/fl_tool.py --source /app/pipeweave --test-file /app/test_suite.py --threshold 0.6

# Step 3: Fix the bugs guided by localization results
python3 /solution/fix_bugs.py
