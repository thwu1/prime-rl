#!/usr/bin/env bash

export FOAM_SIGFPE=false

# Source OpenFOAM environment
. /usr/lib/openfoam/openfoam2312/etc/bashrc 2>/dev/null || true

if ! command -v blockMesh &>/dev/null; then
    echo "ERROR: blockMesh not found in PATH after sourcing OpenFOAM"
    exit 1
fi

cd /app/cavity

# Apply all five configuration fixes
python3 /solution/fix_cavity.py

# Copy the convergence analysis script into place
cp /solution/analyze.py /app/analyze.py

# Clean any previous runs
rm -rf constant/polyMesh processor* [1-9]* [1-9]*.[0-9]* log.* postProcessing

# Run the mesh convergence study (produces /app/convergence_report.json)
cd /app
python3 /app/analyze.py

echo "Solution complete."
