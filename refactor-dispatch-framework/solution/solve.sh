#!/bin/bash

set -e

cd /app

# Run the refactoring script
python3 /solution/refactor.py

# Build and verify
make clean
make
echo "--- Refactored build successful ---"
./cmdproc
echo "--- Refactored binary runs correctly ---"
