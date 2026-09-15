#!/usr/bin/env bash

set -e

python3 /solution/solve_helper.py

echo "Verifying with coqc..."
coqc /app/AIG.v
echo "All proofs accepted."
