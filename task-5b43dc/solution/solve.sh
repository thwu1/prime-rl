#!/bin/bash

set -e

cd /app

# Run pure Python solution: computes symbolic Cholesky under natural,
# AMD (minimum degree), and RCM orderings for each matrix.
python3 /solution/solve_all.py
