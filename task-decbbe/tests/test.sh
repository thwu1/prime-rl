#!/usr/bin/env bash

pip3 install pytest==8.3.4 radon==6.0.1 -q

# Restore critical files from backup if accidentally deleted
for f in models.py specification.md run_scenario.py; do
    if [ ! -f "/app/$f" ]; then
        cp "/opt/task_data/$f" "/app/$f" 2>/dev/null || true
    fi
done

export PYTHONPATH=/app:${PYTHONPATH:-}

cd /app

RESULT=$(python3 -m pytest /tests/test_state.py -v --tb=short --rootdir=/app 2>&1)
EXIT_CODE=$?

echo "$RESULT"

mkdir -p /logs/verifier

if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
