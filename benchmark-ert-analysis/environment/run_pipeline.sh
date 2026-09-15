#!/bin/bash
# COCO benchmarking pipeline orchestrator
# Builds the data converter, imports TSV data into SQLite, and runs analysis.
set -e

echo "=== Step 1: Build data converter ==="
cd /app/converter
make
echo ""

echo "=== Step 2: Import TSV data into SQLite ==="
rm -f /app/benchmark.db
./converter /app/raw_data/metadata.json /app/raw_data /app/benchmark.db
echo ""

echo "=== Step 3: Run analysis pipeline ==="
python3 /app/pipeline/main.py
echo ""

echo "=== Pipeline complete ==="
