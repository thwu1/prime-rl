#!/bin/bash

pip3 install numpy==2.1.3 -q

# Extract source archive for reference (solver reads Rust source)
cd /app && tar xzf src.tar.gz 2>/dev/null || true

# Deploy and run the solution
cp /solution/solver.py /app/fill_simulator.py
python3 /app/fill_simulator.py
