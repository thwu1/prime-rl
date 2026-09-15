#!/bin/bash

# Copy the reference solution into place
cp /solution/ops_solution.py /app/ops.py

# Run training
cd /app && python3 train.py
