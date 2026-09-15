#!/bin/bash

# Step 1: Profile the original binary with cachegrind and generate analysis
python3 /solution/generate_analysis.py

# Step 2: Install the optimized pipeline implementation
cp /solution/optimized_pipeline.c /app/pipeline.c

# Step 3: Rebuild with optimized code
cd /app && make clean && make
