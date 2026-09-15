#!/bin/bash

set -e

cd /app

# Fix all defects and produce root cause analysis
python3 /solution/fix_pipeline.py

# Verify by running the simulation (exits 0 on success)
python3 /app/run_simulation.py
