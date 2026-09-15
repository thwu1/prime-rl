#!/usr/bin/env bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

cd /app

# Step 1: Diagnose and fix the forcing function error in problem_spec.py
python3 /solution/fix_spec.py

# Step 2: Run the FEM solver convergence study
python3 /solution/solver.py
