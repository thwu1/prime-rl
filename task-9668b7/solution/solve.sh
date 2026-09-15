#!/bin/bash

# Deploy the DSE analyzer implementation
cp /solution/dse_solution.py /app/dse_analyzer.py

# Run the full analysis pipeline to verify it works
python3 /app/dse_analyzer.py --config /app/dse_config.yaml --output /app/results.json

echo "Solution deployed and verified."
