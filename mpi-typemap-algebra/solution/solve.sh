#!/bin/bash

# Fix the Makefile to use the MPI compiler wrapper instead of gcc
sed -i 's/^CC = gcc$/CC = mpicc/' /app/Makefile

# Compile the MPI validation program
make -C /app clean
make -C /app

# Run the MPI validation to generate ground truth
mpirun --allow-run-as-root -np 1 /app/mpi_validate

# Apply the corrected Python MPI type algebra implementation
cp /solution/mpi_types_fixed.py /app/mpi_types.py

# Run the Python analysis to produce results.json
python3 /app/run_analysis.py
