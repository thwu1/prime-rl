#!/bin/bash

EXITCODE=0
python3 -m pytest /tests/test_state.py -v --tb=short || EXITCODE=$?

mkdir -p /logs/verifier
if [ $EXITCODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXITCODE
