#!/bin/bash

pip3 install mpmath==1.3.0 -q

# Run the audit and generate the report
python3 /solution/solve.py

# Compile the fixed library
gcc -shared -fPIC -O2 -o /app/libfpmath_fixed.so /solution/fpmath_fixed.c -lm
