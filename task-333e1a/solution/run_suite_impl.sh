#!/bin/bash


DB="/app/results.db"
SUITE="/app/test_suite.json"

# Create database schema
rm -f "$DB"
sqlite3 "$DB" "CREATE TABLE results (
    id TEXT PRIMARY KEY,
    fen TEXT NOT NULL,
    expected_moves TEXT NOT NULL,
    engine_move TEXT DEFAULT '',
    correct INTEGER NOT NULL DEFAULT 0,
    depth INTEGER NOT NULL,
    time_ms INTEGER DEFAULT 0
);"

# Get number of positions
count=$(jq 'length' "$SUITE")
echo "Processing $count positions..."

for i in $(seq 0 $((count - 1))); do
    # Extract position data with jq
    id=$(jq -r ".[$i].id" "$SUITE")
    fen=$(jq -r ".[$i].fen" "$SUITE")
    depth=$(jq -r ".[$i].depth" "$SUITE")
    expected_csv=$(jq -r ".[$i].expected_moves | join(\",\")" "$SUITE")

    echo -n "  [$((i+1))/$count] $id (depth $depth)... "

    # Run engine and capture bestmove
    start_ms=$(date +%s%3N)
    bestmove=$(printf 'uci\nisready\nposition fen %s\ngo depth %s\nquit\n' \
        "$fen" "$depth" | \
        timeout 120 python3 /app/engine.py 2>/dev/null | \
        grep '^bestmove' | head -1 | awk '{print $2}') || true
    end_ms=$(date +%s%3N)
    time_ms=$((end_ms - start_ms))

    # Default to empty string if bestmove not found
    bestmove="${bestmove:-}"

    # Check if bestmove is in expected moves
    correct=0
    IFS=',' read -ra expected_arr <<< "$expected_csv"
    for exp in "${expected_arr[@]}"; do
        if [ "$bestmove" = "$exp" ]; then
            correct=1
            break
        fi
    done

    if [ $correct -eq 1 ]; then
        echo "PASS ($bestmove, ${time_ms}ms)"
    else
        echo "FAIL (got '$bestmove', expected one of: $expected_csv, ${time_ms}ms)"
    fi

    # Insert into SQLite
    sqlite3 "$DB" "INSERT INTO results (id, fen, expected_moves, engine_move, correct, depth, time_ms)
        VALUES ('$id', '$(echo "$fen" | sed "s/'/''/g")', '$expected_csv', '${bestmove:-}', $correct, $depth, $time_ms);"
done

echo "Suite complete. Results stored in $DB"
