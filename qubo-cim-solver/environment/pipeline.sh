#!/bin/bash
# Pipeline: build format converter, convert instances, run solver

set -e

# Step 1: Build Rust format converter
cd /app/converter
cargo build --release

# Step 2: Convert text-format instances to JSON
./target/release/converter /app/raw_instances /app/instances

# Step 3: Run optimization solver
cd /app
python3 solver.py
