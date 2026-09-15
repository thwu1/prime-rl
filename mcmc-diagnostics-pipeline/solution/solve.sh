#!/bin/bash

# Copy the corrected diagnostics module into place
cp /solution/fixed_diagnostics.py /app/diagnostics.py

# Run the analysis pipeline
cd /app
python3 run_analysis.py
