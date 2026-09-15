#!/bin/bash

pip3 install pytest==8.3.4 -q

# Verify the reconciliation tool exists
if [ ! -f /app/reconcile.py ]; then
    echo "ERROR: /app/reconcile.py not found"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Only run reconcile.py if it has not already been executed.
# Re-running it after the database has been repaired would produce a
# near-empty audit report (most discrepancies already fixed), overwriting
# the correct report the agent or solve.sh generated on the original data.
cd /app
if [ ! -f /app/audit_report.json ]; then
    python3 /app/reconcile.py
    TOOL_EXIT=$?
    if [ $TOOL_EXIT -ne 0 ]; then
        echo "ERROR: reconcile.py exited with code $TOOL_EXIT"
        mkdir -p /logs/verifier
        echo "0.0" > /logs/verifier/reward.txt
        exit 1
    fi
fi

# Run verification tests
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
