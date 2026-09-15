#!/bin/bash

set -e

pip3 install numpy==2.1.3 -q

# Deploy solution modules
cp /solution/peaks.c /app/peaks.c
cp /solution/Makefile /app/Makefile
cp /solution/gmpb_impl.py /app/gmpb.py
cp /solution/optimizer_impl.py /app/optimizer.py
cp /solution/run_impl.py /app/run.py

# Build the C shared library
cd /app
make

# Run the optimizer on all instances
python3 /app/run.py
