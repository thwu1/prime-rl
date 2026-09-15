#!/usr/bin/env bash

set -e
cd /app

# Step 1: Parse heterogeneous data files, detect unsolvable instances
python3 /solution/preprocess.py

# Step 2: Compile the PDB-based optimal solver
gcc -O2 -o /app/pdb_solver /solution/solver.c

# Step 3: Run solver on solvable instances
/app/pdb_solver < /tmp/solvable_input.txt > /tmp/raw_output.txt

# Step 4: Assemble results.json
python3 /solution/postprocess.py

echo "Done. Results written to /app/results.json"
