#!/bin/bash
# Orchestrate the JSP solver pipeline:
#   1. Convert each OR-Library instance to GMPL data
#   2. Solve the MIP with glpsol
#   3. Parse the solution into a schedule CSV

INSTANCE_DIR="/app/instances"
DATA_DIR="/app/data"
SOLUTION_DIR="/app/solutions"
OUTPUT_DIR="/app/output"

mkdir -p "$DATA_DIR" "$SOLUTION_DIR" "$OUTPUT_DIR"

for instance_file in "$INSTANCE_DIR"/*.txt; do
    name=$(basename "$instance_file" .txt)
    echo "=== Solving $name ==="

    # Step 1: generate GMPL data file
    python3 /app/pipeline/generate_data.py \
        "$instance_file" "$DATA_DIR/$name.dat"

    # Step 2: solve MIP
    glpsol --model /app/pipeline/jsp.mod \
           --data "$DATA_DIR/$name.dat" \
           --output "$SOLUTION_DIR/$name.sol" \
           --tmlim 10

    if [ $? -ne 0 ]; then
        echo "ERROR: glpsol failed for $name"
        continue
    fi

    # Step 3: extract schedule
    python3 /app/pipeline/parse_solution.py \
        "$instance_file" "$SOLUTION_DIR/$name.sol" "$OUTPUT_DIR/$name.csv"

    echo "--- Done $name ---"
    echo ""
done
