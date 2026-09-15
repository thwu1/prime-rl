#!/usr/bin/env bash

pip3 install pytest==8.3.4 -q

cd /app
pytest /tests/test_state.py -v
rc=$?

mkdir -p /logs/verifier
if [ $rc -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $rc
