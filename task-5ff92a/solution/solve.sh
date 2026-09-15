#!/bin/bash

# Generate the P-256 Montgomery arithmetic implementation,
# Makefile, and toolchain helper scripts
python3 /solution/generate_solution.py

# Build everything using the Makefile
cd /app
make all static check-symbols analyze verify-prime
