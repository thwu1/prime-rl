#!/bin/bash

pip3 install numpy==2.1.3 -q

cp /solution/riemann.py /app/riemann.py
cp /solution/kt_solver.py /app/kt_solver.py
cp /solution/run_analysis.py /app/run_analysis.py

cd /app
python3 run_analysis.py
