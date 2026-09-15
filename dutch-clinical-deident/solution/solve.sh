#!/bin/bash

# No additional pip dependencies needed — solution uses only stdlib

# Copy solution script to where the task expects it
cp /solution/deidentify_solution.py /app/deidentify.py

# Run the pipeline to generate de-identified output
cd /app
python3 /app/deidentify.py
