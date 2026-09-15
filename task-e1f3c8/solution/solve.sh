#!/bin/bash

cd /app
mkdir -p /app/output

# Compute authority graph and generate DOT visualization
python3 /solution/analyzer.py

# Render DOT to SVG using graphviz
dot -Tsvg /app/output/authority.dot -o /app/output/authority.svg

# Generate Z3 SMT-LIB2 verification file and run Z3
python3 /solution/z3gen.py
z3 /app/output/invariants.smt2 > /app/output/z3_output.txt 2>&1
