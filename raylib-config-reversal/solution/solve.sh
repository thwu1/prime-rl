#!/bin/bash

set -e

# --- Part 1: Analyze the target library configuration ---
echo "=== Part 1: Analyzing target library configuration ==="
python3 /solution/analyze_config.py

# --- Part 2: Build and run the image processing pipeline ---
echo "=== Part 2: Building image processing pipeline ==="

# Compile the pipeline program against the target library
gcc /solution/pipeline.c \
    -I/app/target \
    -L/app/target \
    -lraylib \
    -lGL -lm -lpthread -ldl -lrt -lX11 \
    -o /app/pipeline

echo "Pipeline binary compiled at /app/pipeline"

# Create output directory if needed
mkdir -p /app/output

# Run the pipeline
echo "Running pipeline..."
cd /app
./pipeline

echo "=== Done ==="
echo "Outputs:"
echo "  /app/analysis/config_report.json"
echo "  /app/output/result.png"
echo "  /app/output/report.txt"
echo "  /app/pipeline"

# Show the report
echo ""
echo "=== Pixel Report ==="
cat /app/output/report.txt
