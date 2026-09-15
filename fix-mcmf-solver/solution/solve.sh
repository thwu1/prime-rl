#!/bin/bash

set -e

# Step 1: Fix Python MCMF solver (replace with corrected version)
cp /solution/correct_mcmf.py /app/solvers/mcmf.py

# Step 2: Fix Makefile and compile C++ solver
cd /app/solvers
sed -i 's/c++11/c++17/' Makefile
sed -i 's/mcmf_solver\.cpp/mcmf.cpp/' Makefile
make
cd /app

# Step 3: Generate instance summary using jq
for f in /app/instances/instance_1.json /app/instances/instance_2.json /app/instances/instance_3.json; do
    name=$(basename "$f" .json)
    jq --arg name "$name" '{
        name: $name,
        num_sources: (.sources | length),
        num_sinks: (.sinks | length),
        num_hubs: (.hubs | length),
        num_edges: (.edges | length),
        total_supply: ([.sources[].supply] | add),
        total_demand: ([.sinks[].demand] | add)
    }' "$f"
done | jq -s '.' > /app/instance_summary.json

# Step 4: Solve instances, evaluate proposed solutions, populate SQLite database
python3 /solution/solver.py
