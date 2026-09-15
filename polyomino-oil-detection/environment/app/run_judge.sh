#!/bin/bash
# Run solver against all pre-generated instances and display results.
# Usage: bash run_judge.sh ["python3 /app/solver.py"]

SOLVER="${1:-python3 /app/solver.py}"
for i in 0 1 2 3 4; do
    echo "=== Instance $i ==="
    python3 /app/judge.py "/app/instances/instance_$i.json" "$SOLVER"
    echo ""
done
