#!/bin/bash

set -e

# No additional pip deps needed for the solution

cd /app

# Run the solution helper
python3 /solution/solve_helper.py

echo "Solution complete."
