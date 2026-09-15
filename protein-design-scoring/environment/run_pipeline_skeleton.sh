#!/bin/bash
set -euo pipefail

CONFIG="/app/config.json"

# Stage 1: Normalize PAE prediction files to a uniform JSON format
mkdir -p /app/pae_normalized
# TODO: Process each file in /app/pae/ into /app/pae_normalized/


# Stage 2: Compute structural metrics
python3 /app/metrics.py "$CONFIG"


# Stage 3: Score and rank designs in a database
# TODO: Create /app/designs.db and execute /app/pipeline.sql


# Stage 4: Export ranked results as JSON to /app/results.json
# TODO: Query the database and write results matching expected_results.json schema


echo "Pipeline complete."
