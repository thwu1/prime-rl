#!/usr/bin/env bash

set -e

# Copy solved implementations into /app/
cp /solution/zne_inference_solved.py /app/zne_inference.py
cp /solution/analyze_solved.py /app/analyze.py

# Run the pipeline
cd /app
python3 analyze.py
