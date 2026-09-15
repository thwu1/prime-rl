#!/bin/bash

# Study the Go WAL source to understand the binary format
echo "=== Inspecting Go WAL source ==="
head -30 /app/gowal/wal.go

# Run the Go verifier on each node to identify corruption
echo "=== Verifying each node ==="
for node in /app/cluster/node_*; do
    echo "--- $(basename $node) ---"
    /app/gowal/gowal verify --dir "$node" 2>&1 || true
done

# Deploy the reconciler
cp /solution/reconciler.py /app/wal_reconciler.py

# Run reconciliation
cd /app
python3 /app/wal_reconciler.py /app/cluster
