#!/bin/bash

# Ensure /app/src directory exists
mkdir -p /app/src

cd /app

# Apply fixes to all five kernels and verify
python3 /solution/fix_kernels.py
