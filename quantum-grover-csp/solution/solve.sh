#!/bin/bash

pip3 install qiskit==1.2.4 qiskit-aer==0.15.1 -q

cp /solution/solver.py /app/quantum_solver.py
cd /app
python3 quantum_solver.py
