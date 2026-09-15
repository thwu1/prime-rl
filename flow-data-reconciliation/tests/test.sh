#!/bin/bash

pip3 install --break-system-packages pytest==8.3.4 -q 2>&1 || \
    python3 -m pip install --break-system-packages pytest==8.3.4 -q 2>&1

# Run the solution if output doesn't already exist
if [ ! -f /app/results/reconciled_values.csv ]; then
    if [ -f /app/reconcile.py ]; then
        cd /app && python3 reconcile.py 2>&1 || true
    elif [ -f /solution/solve.sh ]; then
        bash /solution/solve.sh 2>&1 || true
    fi
fi

cd /app
python3 -m pytest /tests/test_state.py -v
exit_code=$?

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $exit_code
