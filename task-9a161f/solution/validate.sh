#!/bin/bash

# Build verification tool if needed
if [ ! -x /app/tools/undead-tool ]; then
    cd /app/tools && make -s undead-tool
fi

cd /app

# Run generator to produce puzzles in /app/generated/
mkdir -p /app/generated
python3 /app/generator.py

# Run solver on all puzzles (provided and generated)
mkdir -p /app/solutions
python3 /app/solver.py

# Cross-validate every solution with the C verifier
FAILED=0
for puzzle_dir in puzzles generated; do
    for puzzle in $puzzle_dir/*.txt; do
        [ -f "$puzzle" ] || continue
        name=$(basename "$puzzle")
        game_id=$(cat "$puzzle")
        sol="solutions/$name"
        if [ ! -f "$sol" ]; then
            echo "MISSING: $name" >&2
            FAILED=1
            continue
        fi
        output=$(/app/tools/undead-tool verify "$game_id" "$sol" 2>&1)
        rc=$?
        if [ $rc -eq 0 ]; then
            echo "PASS: $name"
        else
            echo "FAIL: $name - $output" >&2
            FAILED=1
        fi
    done
done

if [ $FAILED -eq 1 ]; then
    echo "Validation FAILED" >&2
    exit 1
fi
echo "All solutions verified."
exit 0
