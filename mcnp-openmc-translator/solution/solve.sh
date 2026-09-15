#!/bin/bash

set -e

# Install solution dependencies
pip3 install scipy==1.14.1 -q

# Set up translator
mkdir -p /app/translator
cp /solution/translator.py /app/translator/mcnp_to_openmc.py

# Translate all benchmarks
for bench in hmf001 hmf003 pmf001 hst001; do
    mkdir -p /app/output/${bench}
    python3 /app/translator/mcnp_to_openmc.py /app/benchmarks/${bench}.mcnp /app/output/${bench}
done

# Run validation analysis
mkdir -p /app/analysis
python3 /solution/analyzer.py /app/data/uncertainties.csv /app/analysis/validation_report.json

echo "Solution complete."
