#!/bin/bash

# Copy solution to /app
cp /solution/solution_impl.py /app/solution.py

# Verify
cd /app && python3 verify.py
