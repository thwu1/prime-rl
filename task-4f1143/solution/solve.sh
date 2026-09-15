#!/bin/bash

pip3 install numpy==2.1.3 -q

# Copy corrected source files
cp /solution/elliptic_core.c /app/elliptic_core.c
cp /solution/elliptic_solution.py /app/elliptic.py

# Recompile C shared library with corrected source
gcc -shared -fPIC -o /app/libelliptic.so /app/elliptic_core.c -lm
