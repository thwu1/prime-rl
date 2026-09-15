#!/usr/bin/env bash

# Solve the streaming consistency audit task:
# 1. Fix pipeline defects
# 2. Build DuckDB batch oracle
# 3. Build and run consistency monitor

pip3 install duckdb==1.1.0 -q

cd /app

# Step 1: Fix pipeline bugs
python3 /solution/fix_pipeline.py

# Step 2: Build DuckDB-based batch oracle
python3 /solution/build_oracle.py

# Step 3: Build and run consistency monitor
python3 /solution/build_monitor.py
