#!/usr/bin/env bash

set -e

pip3 install radon==6.0.1 -q

# Restore models.py from backup if needed
if [ ! -f "/app/models.py" ]; then
    cp "/opt/task_data/models.py" "/app/models.py" 2>/dev/null || true
fi

export PYTHONPATH=/app:${PYTHONPATH:-}
cd /app

# Apply the refactored solution
python3 /solution/apply_solution.py

# Verify cyclomatic complexity across all modules
echo "=== Cyclomatic complexity check ==="
for f in /app/legacy_system.py /app/inventory.py /app/pricing.py /app/persistence.py; do
    if [ -f "$f" ]; then
        echo "--- $(basename $f) ---"
        radon cc -s "$f"
    fi
done
echo ""
echo "Solution applied and verified."
