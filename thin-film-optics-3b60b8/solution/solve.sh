#!/bin/bash

pip3 install numpy==2.1.3 pyyaml==6.0.2 -q

# Copy solution files to /app
cp /solution/matrix_kernel_fixed.c /app/matrix_kernel.c
cp /solution/tmm_impl.py /app/tmm_engine.py
cp /solution/run_analysis.py /app/run_analysis.py
cp /solution/Makefile /app/Makefile

# Build and run via make
cd /app && make all
