#!/bin/bash

# Solve all four issues in the MOESI cache coherence simulator.
# Fixes are derived by analyzing the protocol state machine,
# address interleaving logic, and cache hierarchy architecture.

cd /app

python3 /solution/apply_fixes.py
