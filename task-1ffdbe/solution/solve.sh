#!/bin/bash


pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Compile the C RHS kernel into a shared library
gcc -shared -fPIC -O2 -o /app/solver/c_ext/librhs.so /app/solver/c_ext/brusselator_rhs.c -lm

# Apply bug fixes and implement GMRES
python3 /solution/fix_solver.py

# Verify
cd /app
python3 run_benchmark.py
