#!/bin/bash

set -e
cd /app

# Fix the Makefile: add missing source file and linker flag.
cp /solution/Makefile.fixed Makefile

# Fix the buffer rotation parity check in reference.c.
sed -i 's/(timesteps % 2) != 0/(timesteps % 2) == 0/' reference.c

# Fix the coefficient loop initialization in reference.c.
sed -i 's/int ir = 0;/int ir = 1;/' reference.c

# Install the optimized solver implementation.
cp /solution/solver_impl.c solver.c

# Install the output analysis implementation.
cp /solution/analyze_impl.c analyze.c

# Build
make clean
make

# Run the benchmark
./fdtd3d
