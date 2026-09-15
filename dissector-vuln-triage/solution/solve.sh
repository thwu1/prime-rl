#!/bin/bash

cd /app

# Generate proof-of-vulnerability binary inputs
python3 /solution/gen_povs.py

# Analyze vulnerabilities, write report, and apply source patches
python3 /solution/apply_patches.py

# Rebuild with patches applied
make clean
make all
make asan
