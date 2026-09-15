#!/bin/bash

# Copy solution files to /app
cp /solution/c_harness.c /app/c_harness.c
cp /solution/c_pipeline.py /app/c_pipeline.py
cp /solution/rust_pipeline.py /app/rust_pipeline.py
cp /solution/analyzer.py /app/analyzer.py

# Compile the C verification harness
gcc -o /app/c_harness /app/c_harness.c -lm

# Run the analyzer to generate the divergence report
cd /app
python3 analyzer.py
