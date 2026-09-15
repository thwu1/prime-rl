#!/bin/bash

pip3 install numpy==2.1.3 -q

cp /solution/solver.py /app/solver_ref.py
python3 /app/solver_ref.py
