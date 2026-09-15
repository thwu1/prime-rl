#!/bin/bash

# Create the evaluator package
mkdir -p /app/evaluator

# Copy solution modules
cp /solution/__init__.py /app/evaluator/
cp /solution/injection.py /app/evaluator/
cp /solution/scoring.py /app/evaluator/
cp /solution/analysis.py /app/evaluator/
cp /solution/pipeline.py /app/evaluator/

# Run the pipeline
cd /app && python3 -c "from evaluator.pipeline import run_pipeline; run_pipeline('/app/data', '/app/output')"
