#!/bin/bash

pip3 install numpy==2.1.3 -q

cd /app

# Step 1: Fix all bugs in the analog pipeline
python3 /solution/fix_pipeline.py

# Step 2: Create the digital filter module
python3 /solution/create_digitize.py

# Step 3: Run the minimum-order analysis and write results.json
python3 /solution/run_analysis.py
