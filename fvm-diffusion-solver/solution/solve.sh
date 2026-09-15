#!/usr/bin/env bash


pip3 install numpy==1.26.4 scipy==1.13.1 -q

# Copy solver to /app/
cp /solution/fvm_solver.py /app/solver.py

cd /app
python3 /app/solver.py --study
