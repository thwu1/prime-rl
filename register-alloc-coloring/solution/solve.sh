#!/bin/bash

# No additional pip deps needed — solution is pure Python using only stdlib

# Write the four implementation files
python3 /solution/write_implementations.py

echo "Solution implementations written to /app/"
echo "Running local tests..."
python3 /app/test_local.py
echo "Local tests passed."
