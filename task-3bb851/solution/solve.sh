#!/bin/bash

set -e
cd /app

# Write the three analysis tools
python3 /solution/solution.py

echo "Solution complete. Running tools..."

# Run analyzer
python3 /app/fdb_analyzer.py

# Run spec validator
python3 /app/fdb_spec_validator.py

# Run orchestrator
python3 /app/fdb_orchestrator.py

echo "All tools executed. Results in /app/results/"
ls -la /app/results/
