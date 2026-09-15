#!/bin/bash

# Generate the complete solution with all proofs
python3 /solution/generate_solution.py

# Compile to verify correctness
cd /app && coqc MerkleTree.v
