#!/bin/bash

# Copy the solution analyzer to /app/
cp /solution/analyzer_solution.py /app/combench_analyzer.py

# Run the pipeline
python3 /app/combench_analyzer.py
