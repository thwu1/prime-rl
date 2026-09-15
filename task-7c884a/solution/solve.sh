#!/bin/bash

set -e

# Create the complete test suite and analysis
python3 /solution/create_suite.py

# Verify the suite by running lit
echo ""
echo "=== Running lit to verify test suite ==="
lit /app/tests/ -v
echo ""
echo "All tests pass."
echo ""
echo "=== Analysis results ==="
cat /app/analysis.json
