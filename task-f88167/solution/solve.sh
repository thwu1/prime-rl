#!/bin/bash

set -e

mkdir -p /tmp/sokoban_levels /tmp/sokoban_solutions

# Step 1: Extract levels from the SQLite database into text files
echo "Extracting levels from database..." >&2
python3 /solution/db_extract.py

# Step 2: Solve each level
for i in 1 2 3 4; do
    echo "Solving level ${i}..." >&2
    python3 /solution/solver.py "/tmp/sokoban_levels/level_${i}.txt" "/tmp/sokoban_solutions/level_${i}.txt"
done

# Step 3: Insert solutions back into the database
echo "Inserting solutions into database..." >&2
python3 /solution/db_insert.py

# Step 4: Run the validation pipeline
echo "Running validation pipeline..." >&2
bash /app/tools/validate.sh

echo "All done." >&2
