#!/usr/bin/env bash

# Step 1: Compile the binary decoder
cd /app/tools && make

# Step 2: Run the full evaluation pipeline
cd /app
python3 /solution/icfp_eval.py
