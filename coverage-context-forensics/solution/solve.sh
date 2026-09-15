#!/bin/bash

pip3 install pytest==8.3.4 coverage==7.6.1 -q

cd /app

# Step 1: Fix the broken .coveragerc
python3 /solution/fix_config.py

# Step 2: Clean any prior coverage data
coverage erase
rm -f .coverage.*

# Step 3: Run test suite under coverage
coverage run -m pytest tests/ -v

# Step 4: Combine parallel coverage data from multiprocessing workers
coverage combine

# Step 5: Produce the impact analysis report
python3 /solution/analyze.py
