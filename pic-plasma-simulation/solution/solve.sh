#!/bin/bash

cd /app
pip3 install numpy==2.1.3 -q

# Apply all fixes: C kernel, Makefile, Python framework, gnuplot script
python3 /solution/fix_all.py

# Build C shared library
make clean 2>/dev/null
make

# Run Langmuir plasma oscillation simulation
python3 run_langmuir.py

# Run two-stream instability simulation
python3 run_two_stream.py

# Generate phase-space plot with gnuplot
gnuplot plot_phase_space.gp
