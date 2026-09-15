#!/bin/bash

cd /app
mkdir -p /app/models /app/bounds /app/visualizations /app/solutions

# Deploy GMPL model to working directory
cp /solution/vrp_lp.mod /app/models/vrp_lp.mod

# Run the complete solver pipeline
python3 /solution/solver.py
