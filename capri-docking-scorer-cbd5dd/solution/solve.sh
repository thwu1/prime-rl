#!/bin/bash

set -e

cd /app

# Copy the fixed C++ implementation
cp /solution/capri_scorer_fixed.cpp /app/capri_scorer.cpp

# Compile
make clean
make

echo "Build complete. Running quick sanity check..."
./capri_scorer /app/data/reference.pdb /app/data/model.pdb A B 5.0
