#!/bin/bash

# Compile the C shared library
gcc -shared -fPIC -O2 -o /app/libbrc.so /solution/brc.c

# Copy Python files to /app
cp /solution/brc_engine.py /app/brc_engine.py
cp /solution/run_analysis.py /app/run_analysis.py

# Run the analysis to produce results.json
cd /app
python3 run_analysis.py
