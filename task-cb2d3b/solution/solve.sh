#!/bin/bash

pip3 install numpy==2.1.3 h5py==3.11.0 -q

cp /solution/mhd_solver.py /app/
cp /solution/Makefile /app/
mkdir -p /app/output
cp /solution/density.gp /app/output/
cp /solution/divB.gp /app/output/

cd /app && make all
