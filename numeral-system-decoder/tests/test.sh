#!/bin/bash

pytest /tests/test_state.py -v
EXITCODE=$?

mkdir -p /logs/verifier
if [ $EXITCODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXITCODE
