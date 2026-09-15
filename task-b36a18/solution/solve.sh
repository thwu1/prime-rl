#!/bin/bash

set -e

# Fix the 4 bugs in the CUBIC implementation
python3 /solution/fix_cubic.py

# Run the simulation to verify correct behavior
python3 /app/simulate.py
