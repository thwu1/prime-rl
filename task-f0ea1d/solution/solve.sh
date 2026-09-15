#!/bin/bash

set -e
cd /app

# Apply all fixes and implementations via Python helper
python3 /solution/implement.py

# Build
make clean && make
