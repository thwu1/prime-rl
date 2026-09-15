#!/bin/bash

# Replace the buggy skeleton with the correct implementation
cp /solution/persistent_segtree_fixed.rs /app/src/persistent_segtree.rs

cd /app
cargo build --release 2>&1
if [ $? -ne 0 ]; then
    echo "Compilation failed"
    exit 1
fi

echo "=== Running all test cases ==="
for f in /app/data/test*.in; do
    name=$(basename "$f" .in)
    expected="/app/data/${name}.out"
    echo "--- $name ---"
    actual=$(./target/release/persistent_segtree < "$f")
    echo "$actual"
    if [ -f "$expected" ]; then
        expected_content=$(cat "$expected" | tr -s '[:space:]' '\n' | sed '/^$/d')
        actual_content=$(echo "$actual" | tr -s '[:space:]' '\n' | sed '/^$/d')
        if [ "$actual_content" = "$expected_content" ]; then
            echo "PASS"
        else
            echo "FAIL"
            echo "Expected: $expected_content"
            echo "Actual: $actual_content"
            exit 1
        fi
    fi
    echo ""
done
