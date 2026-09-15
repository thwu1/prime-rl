#!/bin/bash

# Fix all five configuration bugs in the backward-facing step case
python3 /solution/fix_case.py

# Source OpenFOAM environment
source /opt/openfoam12/etc/bashrc

cd /app/backwardStep

# Clean any previous results
for d in [0-9]*; do
    [ "$d" != "0" ] && [ -d "$d" ] && rm -rf "$d"
done
rm -f log.* validation_report.json

# Regenerate mesh
blockMesh > log.blockMesh 2>&1

# Run the steady-state incompressible solver to convergence
foamRun -solver incompressibleFluid > log.solver 2>&1
echo "Solver exit code: $?"

# Deploy and run the validation pipeline
cp /solution/validate.py /app/backwardStep/validate.py
python3 /app/backwardStep/validate.py
