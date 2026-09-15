#!/bin/bash

# Copy solution files to working directory
cp /solution/hfo2_rram.py /app/hfo2_rram.py
cp /solution/error_decomposition.py /app/error_decomposition.py

# Run the error decomposition analysis
cd /app
python3 /app/error_decomposition.py
