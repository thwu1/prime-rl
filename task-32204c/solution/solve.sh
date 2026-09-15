#!/bin/bash

mkdir -p /app/output

# Copy and run the solution pipeline
cp /solution/solver.py /app/solver.py
python3 /app/solver.py
