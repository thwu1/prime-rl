#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app

# Run the agent's scripts if they exist (repair -> optimize -> retention)
if [ -f /app/repair_db.py ]; then
    python3 /app/repair_db.py
fi
if [ -f /app/optimize_db.py ]; then
    python3 /app/optimize_db.py
fi
if [ -f /app/retention.py ]; then
    python3 /app/retention.py
fi

# Run tests
python3 -m pytest /tests/test_state.py -v
exit_code=$?

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $exit_code
