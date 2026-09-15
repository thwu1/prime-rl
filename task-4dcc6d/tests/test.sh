#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Source OpenFOAM environment
source /opt/openfoam12/etc/bashrc

cd /app/backwardStep

# Clean previous solver results (keep 0/ directory and constant/)
for d in [0-9]*; do
    [ "$d" != "0" ] && [ -d "$d" ] && rm -rf "$d"
done
rm -f log.solver log.blockMesh validation_report.json

# Regenerate mesh from blockMeshDict
blockMesh > log.blockMesh 2>&1
MESH_EXIT=$?

if [ $MESH_EXIT -ne 0 ]; then
    echo "blockMesh failed — mesh generation error"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

# Run the solver
foamRun -solver incompressibleFluid > log.solver 2>&1

# Run the agent's validate.py if it exists to regenerate the report
if [ -f /app/backwardStep/validate.py ]; then
    python3 /app/backwardStep/validate.py
fi

# Run pytest verification
pytest /tests/test_state.py -v
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
