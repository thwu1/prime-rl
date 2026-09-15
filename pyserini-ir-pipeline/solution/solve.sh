#!/bin/bash

export PIP_BREAK_SYSTEM_PACKAGES=1

cd /app

echo "=== Running IR diagnosis and optimization ==="
python3 /solution/solve_helper.py
echo "=== Done ==="
