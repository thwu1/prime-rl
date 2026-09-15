#!/usr/bin/env bash


pip3 install numpy==2.1.3 -q

# Fix the Python module
python3 /solution/solve_elliptic.py

# Fix the Makefile (add missing math library linkage) and build C tool
sed -i '/^LDFLAGS/s/=.*/= -lm/' /app/Makefile
cd /app && make clean && make

# Generate ZPK files from the corrected module
cd /app && python3 /app/gen_zpk.py

# Generate the validation report using the C analyzer
python3 /solution/solve_validate.py
