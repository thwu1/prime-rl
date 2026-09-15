#!/bin/bash

# Fix C source code and build system
cp /solution/cubic_solver_fixed.c /app/libcubic/cubic_solver.c
cp /solution/Makefile_fixed /app/libcubic/Makefile

# Compile the C shared library
make -C /app/libcubic clean
make -C /app/libcubic

# Copy Python solution files
cp /solution/pr_mix_solution.py /app/pr_mix.py
cp /solution/flash_cli_solution.py /app/flash_cli.py
