#!/bin/bash

# Copy fixed C source
cp /solution/balance_core_fixed.c /app/src/balance_core.c

# Build shared library with correct flags (including -lm)
cd /app && gcc -Wall -O2 -fPIC -shared -o libbalance.so src/balance_core.c -lm

# Install Python solver
cp /solution/solver.py /app/balance_solver.py
