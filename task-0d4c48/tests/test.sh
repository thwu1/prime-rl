#!/bin/bash

pip3 install pytest==8.3.4 pyyaml==6.0.2 -q

cd /app

pytest /tests/test_state.py -v --tb=short
exit_code=$?

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $exit_code
