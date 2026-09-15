#!/bin/bash


pip3 install numpy==2.1.3 netCDF4==1.7.2 -q

cp /solution/solver.py /app/simulate.py
python3 /app/simulate.py
