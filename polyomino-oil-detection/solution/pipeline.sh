#!/bin/bash
#
# Orchestration pipeline: build C library, run solver, store results in SQLite.
# Uses: make, jq, sqlite3

set -e

cd /app

# Step 1: Build C scoring library
echo "=== Building scoring library ==="
make -C /app

# Step 2: Initialize SQLite database
echo "=== Initializing database ==="
rm -f /app/results.db
sqlite3 /app/results.db "CREATE TABLE IF NOT EXISTS results (
    instance_name TEXT PRIMARY KEY,
    grid_size INTEGER,
    num_fields INTEGER,
    epsilon REAL,
    solved INTEGER,
    cost REAL,
    normalized_cost REAL,
    num_ops INTEGER
);"

# Step 3: Run solver on each instance
for instance in /app/instances/instance_*.json; do
    name=$(basename "$instance" .json)
    echo "=== Running solver on $name ==="

    # Extract instance parameters with jq
    grid_size=$(jq '.N' "$instance")
    num_fields=$(jq '.M' "$instance")
    epsilon=$(jq '.epsilon' "$instance")

    # Run solver and capture judge output
    result=$(python3 /app/judge.py "$instance" "python3 /app/solver.py")

    # Parse result with jq
    solved=$(echo "$result" | jq '.solved')
    cost=$(echo "$result" | jq '.cost')
    norm_cost=$(echo "$result" | jq '.normalized_cost')
    ops=$(echo "$result" | jq '.ops')

    # Convert boolean to integer for SQLite
    if [ "$solved" = "true" ]; then
        solved_int=1
    else
        solved_int=0
    fi

    # Insert into SQLite
    sqlite3 /app/results.db "INSERT OR REPLACE INTO results VALUES (
        '$name', $grid_size, $num_fields, $epsilon,
        $solved_int, $cost, $norm_cost, $ops
    );"

    echo "  $name: solved=$solved_int cost=$cost normalized_cost=$norm_cost ops=$ops"
done

# Step 4: Print summary from SQLite
echo ""
echo "=== Results Summary ==="
sqlite3 /app/results.db -header -column "SELECT * FROM results;"
echo ""
sqlite3 /app/results.db "SELECT printf('Average normalized cost: %.4f', AVG(normalized_cost)) FROM results WHERE solved=1;"
echo "=== Pipeline complete ==="
