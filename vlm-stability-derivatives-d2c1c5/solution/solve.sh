#!/bin/bash

pip3 install numpy==2.1.3 -q

# Ensure config.json is at /app (may have been shadowed by volume mount)
cp /data/config.json /app/config.json 2>/dev/null || true

# Deploy corrected standalone solver (replaces buggy modular version)
cp /solution/vlm_impl.py /app/vlm_solver.py
python3 /app/vlm_solver.py /app/config.json /app/results.json
