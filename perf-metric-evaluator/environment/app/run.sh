#!/bin/bash
# Pipeline orchestrator: extract data from SQLite, run evaluation pipeline

echo "=== Step 1: Extracting data from SQLite ==="
bash /app/extract_data.sh

echo "=== Step 2: Running evaluation pipeline ==="
python3 /app/run.py

echo "=== Pipeline complete ==="
