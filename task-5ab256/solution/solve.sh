#!/bin/bash

# Solve the microcode ROM reverse engineering task
cd /app

# Inspect the binary ROM to understand its format
echo "=== Binary ROM inspection ==="
xxd -l 48 rom.bin

# Query the SQLite database for reference
echo ""
echo "=== Database tables ==="
sqlite3 microcode.db ".tables"
echo ""
echo "=== Translation table (first 10) ==="
sqlite3 microcode.db "SELECT * FROM translations LIMIT 10;"
echo ""
echo "=== Known patent words ==="
sqlite3 microcode.db "SELECT addr, logical_hex, section FROM patent_words;"

# Run the solution
echo ""
echo "=== Running solver ==="
python3 /solution/solve.py
