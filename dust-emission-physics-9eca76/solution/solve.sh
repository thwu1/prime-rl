#!/bin/bash

set -e

# Copy corrected FENGSHA module (6 bug fixes + public exports for shared functions)
cp /solution/dust_physics_mod_fixed.f90 /app/dust_physics_mod.f90

# Copy complete K14 module implementation
cp /solution/dust_k14_mod_complete.f90 /app/dust_k14_mod.f90

# Copy complete main driver with K14 dispatch
cp /solution/main_complete.f90 /app/main.f90

# Build
cd /app
make clean
make

# Verify both schemes run
echo "=== FENGSHA output ==="
./dust_emission < /app/scenarios/test_fengsha.txt

echo ""
echo "=== K14 output ==="
./dust_emission < /app/scenarios/test_k14.txt
