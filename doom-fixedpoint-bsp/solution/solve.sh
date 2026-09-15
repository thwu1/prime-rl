#!/bin/bash

set -e

# Apply all bug fixes via Python helper
python3 /solution/fix_bugs.py

# Rebuild
cd /app
make clean
make -j1

echo "Build succeeded after fixes."
