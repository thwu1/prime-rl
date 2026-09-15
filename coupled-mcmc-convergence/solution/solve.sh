#!/bin/bash

# Step 1: Implement the couplings library
python3 /solution/implement.py

# Step 2: Run the benchmark to populate results.db
python3 /app/benchmark.py

# Step 3: Create analysis SQL and optimal proposal
python3 /solution/create_artifacts.py

# Step 4: Verify the proposal passes
python3 /app/evaluate_proposal.py
