#!/bin/bash

cd /app

# Copy solution files
cp /solution/bpf_sim.py /app/bpf_sim.py

# Run the main solution script
python3 /solution/solve.py
