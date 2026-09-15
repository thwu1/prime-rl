#!/bin/bash

# Copy implementation files to the app
cp /solution/losses_impl.py /app/framework/losses.py
cp /solution/patching_impl.py /app/framework/patching.py
cp /solution/metrics_impl.py /app/framework/metrics.py
cp /solution/analyze_impl.py /app/analyze.py

# Run the analysis pipeline
cd /app && python3 analyze.py
