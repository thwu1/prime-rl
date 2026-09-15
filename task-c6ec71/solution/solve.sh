#!/bin/bash

set -e

# Copy solution C code and build the shared library
cp /solution/quadrature.c /app/quadrature.c
make -C /app clean
make -C /app

# Copy solution Python module
cp /solution/arclength.py /app/arclength.py

# Verify the solution works
cd /app
python3 /app/evaluate.py
