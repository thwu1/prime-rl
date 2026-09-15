#!/bin/bash

pip3 install scipy==1.14.1 numpy==2.1.3 -q

# Copy solver to /app and run
cp /solution/sif_solver.py /app/solve.py
cd /app
python3 /app/solve.py
