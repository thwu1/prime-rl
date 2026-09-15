#!/bin/bash

# Fix the buggy left-right map implementation
python3 /solution/apply_fixes.py

# Deploy sharded map, profiler, and analyzer
cp /solution/sharded_map.py /app/sharded_map.py
cp /solution/profiler.py /app/profiler.py
cp /solution/analyze.py /app/analyze.py

# Run the profiling pipeline
python3 /app/profiler.py

# Run the analysis
python3 /app/analyze.py
