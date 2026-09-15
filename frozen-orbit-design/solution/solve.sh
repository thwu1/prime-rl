#!/bin/bash

python3 /solution/solver.py

# Validate output with jq filter
jq -e -f /app/validate_output.jq /app/results.json > /dev/null
