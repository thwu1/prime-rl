#!/bin/bash

cd /app

# Fix 0: Correct Makefile build order (module dependency)
cp /solution/Makefile_fixed Makefile

# Fix 1-6: Apply corrected Fortran source with all physics fixes
# and pressure field implementation
cp /solution/pekeris_solver_fixed.f90 pekeris_solver.f90

# Rebuild and run
make clean && make
./pekeris_solver
