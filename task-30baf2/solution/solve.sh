#!/bin/bash

cd /app

# Install numpy (should already be installed, but ensure it)
pip3 install numpy==1.26.4 -q

# Deploy the tiled attention engine implementation
cp /solution/engine_impl.py /app/engine.py
echo "Deployed engine.py"

# Deploy the compound mask implementations
cp /solution/compound_masks_impl.py /app/compound_masks.py
echo "Deployed compound_masks.py"

# Generate performance analysis (analysis.json)
python3 /solution/generate_analysis.py

# Generate benchmark database (benchmarks.db)
python3 /solution/generate_benchmarks.py

# Verify with diagnostic sweep
echo ""
echo "Running diagnostic sweep..."
python3 /app/run_checks.py

echo ""
echo "All implementations deployed and verified."
