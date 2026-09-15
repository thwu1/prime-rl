#!/bin/bash

set -e

cd /app

# Determine LAMMPS binary
LAMMPS=""
for cmd in lmp lmp_serial lammps; do
    if command -v "$cmd" &> /dev/null; then
        LAMMPS="$cmd"
        break
    fi
done

if [ -z "$LAMMPS" ]; then
    echo "LAMMPS not found, attempting to install..."
    apt-get update && apt-get install -y lammps
    LAMMPS="lmp"
fi

echo "Using LAMMPS binary: $LAMMPS"

# Copy LAMMPS input scripts from solution directory
cp /solution/in_kappa_mp.lmp /app/in.kappa_mp
cp /solution/in_kappa_heat.lmp /app/in.kappa_heat

# Run Muller-Plathe simulation
echo "=== Running Muller-Plathe thermal conductivity ==="
$LAMMPS -in in.kappa_mp -log log.mp -screen none

# Run fix-heat simulation
echo "=== Running fix-heat thermal conductivity ==="
$LAMMPS -in in.kappa_heat -log log.heat -screen none

# Copy and run analysis script
cp /solution/analyze.py /app/analyze.py
echo "=== Running analysis ==="
python3 /app/analyze.py

echo "=== Done ==="
cat /app/results.json
