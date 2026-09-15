#!/bin/bash

# Build the C eigenvalue library
cp /solution/eigensolve_impl.c /app/csolver/eigensolve.c
make -C /app/csolver clean all

# Install Python solver implementations
cp /solution/minimal_solver_impl.py /app/solver/minimal_solver.py
cp /solution/pose_recovery_impl.py /app/solver/pose_recovery.py
cp /solution/robust_estimator_impl.py /app/solver/robust_estimator.py
