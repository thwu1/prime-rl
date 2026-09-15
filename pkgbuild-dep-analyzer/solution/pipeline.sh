#!/bin/bash
set -e
cd /app
mkdir -p output/srcinfo

# Step 1: Extract PKGBUILD metadata using bash sourcing + jq
bash /app/extract.sh

# Step 2: Analyze ecosystem, generate SRCINFO, render dependency graph
python3 /app/solver.py
