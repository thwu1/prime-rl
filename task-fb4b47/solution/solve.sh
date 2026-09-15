#!/bin/bash

set -e
cd /app
python3 /solution/implement.py

# Build with canaries to verify
make clean 2>/dev/null || true
make CANARIES=1
