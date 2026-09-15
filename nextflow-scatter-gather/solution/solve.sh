#!/bin/bash


set -e

cd /app

# Generate the complete pipeline implementation
python3 /solution/implement_pipeline.py

# Run the pipeline
nextflow run /app/main.nf

# Verify output
if [ -f /app/results/report.json ]; then
    echo "Pipeline completed successfully. Report:"
    cat /app/results/report.json
else
    echo "ERROR: report.json not found"
    exit 1
fi
