#!/bin/bash

set -e

cd /app

# Install the complete parallel solver implementation
cp /solution/solver_parallel_complete.c /app/solver_parallel.c

# Build and run
make clean
make solver_parallel
make run_parallel
