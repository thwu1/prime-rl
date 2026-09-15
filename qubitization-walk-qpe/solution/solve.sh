#!/bin/bash

# Replace the buggy implementation with the correct one
cp /solution/solver.py /app/qubitization.py

# Run the pipeline to produce results.json
cd /app
python3 /app/qubitization.py
