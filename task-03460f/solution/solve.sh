#!/bin/bash

# Solve the SQLMesh pipeline bugs by applying all six fixes programmatically.

python3 /solution/fix_pipeline.py

# Verify the fixes work
cd /app
echo "=== Running sqlmesh test ==="
sqlmesh test
echo "=== Running sqlmesh plan ==="
sqlmesh plan --auto-apply --no-prompts
