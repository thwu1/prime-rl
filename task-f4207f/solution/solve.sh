#!/usr/bin/env bash

# Solution: deploy a complete NMOS 6502 emulator implementation
cp /solution/cpu6502_solution.c /app/cpu6502.c

# Build
cd /app
make clean && make

echo "Solution deployed and compiled."
