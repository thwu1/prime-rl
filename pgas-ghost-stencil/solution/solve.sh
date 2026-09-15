#!/bin/bash

set -e

# Copy the reference implementation into place
cp /solution/pgas_array_impl.c /app/pgas_array.c

# Build
cd /app
make clean
make

# Run with 4 MPI processes
mpirun --allow-run-as-root -n 4 ./laplace_solver

# Verify output was produced
if [ ! -f /app/output.txt ]; then
    echo "ERROR: output.txt was not produced"
    exit 1
fi

echo "Solution completed successfully."
cat /app/output.txt
