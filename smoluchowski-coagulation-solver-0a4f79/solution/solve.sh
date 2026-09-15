#!/bin/bash

pip3 install numpy==2.1.3 netCDF4==1.7.2 -q

cp /solution/coag_solver.py /app/solve.py
cd /app
python3 solve.py
