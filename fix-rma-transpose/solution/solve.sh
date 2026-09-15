#!/bin/bash

# Copy the RMA solution into place and compile
cp /solution/jacobi_rma.c /app/jacobi_rma.c
cd /app
make jacobi_rma

# MPI runner with container-compatible settings
MPIRUN="mpiexec --oversubscribe --allow-run-as-root --mca osc pt2pt --mca btl_vader_single_copy_mechanism none"

echo "=== Reference (sequential) ==="
make jacobi_seq
./jacobi_seq

echo "=== Parallel with 4 processes ==="
$MPIRUN -n 4 ./jacobi_rma

echo "=== Parallel with 6 processes ==="
$MPIRUN -n 6 ./jacobi_rma

echo "=== Anti-cheat: N=48, 4 processes ==="
gcc -Wall -O2 -DN=48 -o jacobi_seq_48 jacobi_seq.c
./jacobi_seq_48
mpicc -Wall -O2 -DN=48 -o jacobi_rma_48 jacobi_rma.c
$MPIRUN -n 4 ./jacobi_rma_48
