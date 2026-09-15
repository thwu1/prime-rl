#!/bin/bash

pip3 install z3-solver==4.13.0.0 -q

# Replace buggy tnum.py with fixed version
cp /solution/tnum_fixed.py /app/tnum.py

# Deploy Z3 verification script
cp /solution/verify_impl.py /app/verify.py

# Run formal verification
cd /app
python3 verify.py
