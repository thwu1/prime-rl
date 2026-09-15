#!/bin/bash

pip3 install sympy==1.13.3 scipy==1.14.1 -q

cp /solution/stokes_solver.py /app/stokes_solver.py
cd /app
python3 stokes_solver.py
