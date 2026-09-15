#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Place the solver where the task expects it
cp /solution/solve_helper.py /app/solver.py

# Run the solver on the main problem
python3 /app/solver.py /app/input /app/output
