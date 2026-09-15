#!/usr/bin/env bash

cd /app

# Install solution dependencies (pinned versions)
pip3 install z3-solver==4.12.6.0

# Deploy optimizer
cp /solution/optimizer.py /app/optimizer.py

# Generate Z3 verification report
python3 /solution/solve_verify.py
