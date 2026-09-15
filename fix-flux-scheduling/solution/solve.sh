#!/bin/bash

# Solve the Flux multi-queue scheduling configuration problem.
# Analyzes the broken config programmatically and generates the fix.

pip3 install tomli==2.2.1 -q 2>/dev/null || true

python3 /solution/fix_config.py
