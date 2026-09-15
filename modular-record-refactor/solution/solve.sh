#!/bin/bash

set -e

cd /app

# Run the refactoring transformation
python3 /solution/refactor.py

# Rebuild with new modular sources
make clean
make

echo "Refactoring complete. Library rebuilt successfully."
