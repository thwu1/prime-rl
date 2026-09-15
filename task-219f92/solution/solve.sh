#!/bin/bash

pip3 install numpy==2.1.3 -q

# Deploy solution files
cp /solution/solver.py /app/solver.py
cp /solution/gen_reference.m /app/octave/gen_reference.m
cp /solution/ks_rhs.m /app/octave/ks_rhs.m
cp /solution/validate.py /app/validate.py
cp /solution/Makefile.complete /app/Makefile

# Run the full pipeline
cd /app
make all
