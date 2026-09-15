#!/bin/bash

cd /app

# Install fixed resolver modules
cp /solution/constraints_fixed.py /app/resolver/constraints.py
cp /solution/solver_fixed.py /app/resolver/solver.py
cp /solution/main_fixed.py /app/resolver/__main__.py

# Verify production Puppetfile resolves
python3 -m resolver resolve /app/Puppetfile

# Verify staging Puppetfile resolves
python3 -m resolver resolve /app/Puppetfile.staging

# Verify circular dependency detection
python3 -m resolver resolve /app/Puppetfile.circular || true

# Generate dependency graph for production
python3 -m resolver resolve --graph /app/deps.dot /app/Puppetfile
dot -Tsvg /app/deps.dot -o /app/deps.svg

# Show conflict explanation for unsatisfiable input
python3 -m resolver resolve --explain /app/Puppetfile.conflict || true
