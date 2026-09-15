#!/bin/bash

pip3 install numpy==2.1.3 -q

# --- Fix text-format instances ---
# The Rust converter outputs "Ising"/"QUBO" but solvers expect lowercase.
# Use Python converter to produce correctly-typed JSON.
python3 /solution/converter.py /app/instances/raw /app/instances

# --- Write verdict evaluating each solver ---
python3 /solution/write_verdict.py

# --- Deploy correct composite solver ---
cp /solution/solver_correct.py /app/solver.py

# --- Run solver on all instances ---
cd /app && python3 solver.py
