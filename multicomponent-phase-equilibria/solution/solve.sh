#!/bin/bash

pip3 install thermo==0.6.0 -q

cp /solution/solver.py /app/phase_solver.py
cd /app
python3 phase_solver.py
