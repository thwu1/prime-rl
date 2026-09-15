#!/usr/bin/env bash

# No additional pip dependencies needed; numpy and scipy are in the image

# Fix pipeline bugs
python3 /solution/fix_pipeline.py

# Implement the distribution selection module
python3 /solution/implement_distselect.py

# Run the corrected pipeline
python3 /app/run_analysis.py
