#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Replace buggy framework with the correct implementation
cp /solution/solve_helper.py /app/framework.py

# Run the optimization
cd /app
python3 run_optimization.py
