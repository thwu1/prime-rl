#!/bin/bash

set -euo pipefail

# Fix verifier bugs
python3 /solution/fix_verifier.py

# Fix bcdump bugs
python3 /solution/fix_bcdump.py

# Deploy complete optimizer implementation
cp /solution/optimizer_impl.c /app/src/optimizer.c

# Rebuild all binaries
make -C /app/src clean
make -C /app/src
