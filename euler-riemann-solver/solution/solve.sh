#!/bin/bash

pip3 install numpy==2.1.3 -q

# Fix solver bugs
cp /solution/exact_riemann.py /app/solver/exact_riemann.py
cp /solution/fv_euler.py /app/solver/fv_euler.py

# Fix Makefile
cp /solution/Makefile /app/Makefile

# Install convergence analysis implementation
cp /solution/analyze.py /app/convergence/analyze.py

# Fix gnuplot script
cp /solution/plot_convergence.gp /app/plot_convergence.gp

# Fix SQLite import script
cp /solution/import_results.sh /app/import_results.sh

# Run the complete pipeline
cd /app && make validate
