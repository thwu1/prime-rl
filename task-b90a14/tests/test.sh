#!/bin/bash

pip3 install pytest==8.3.4 pytest-timeout==2.2.0 -q

cd /app
PYTHONPATH=/app pytest /tests/test_state.py -v --timeout=60
exit_code=$?

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $exit_code
