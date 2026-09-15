#!/bin/bash

# Compile Go verifier
cd /app/btree-tool && go build -o /app/btverify .

# Show corrupted database violations
echo "=== Corrupted database violations ==="
/app/btverify verify /app/database.db || true
echo ""

# Run repair tool
cp /solution/repair.py /app/repair.py
cd /app
python3 /app/repair.py

# Verify repair
echo "=== Repaired database verification ==="
/app/btverify verify /app/database_repaired.db
