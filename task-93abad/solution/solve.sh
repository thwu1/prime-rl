#!/bin/bash

pip3 install mpmath==1.3.0 -q

# Generate the C implementation using Python to compute precise constants
python3 /solution/gen_exp2m1f.py

# Build
cd /app && make clean && make all
