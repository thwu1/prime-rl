#!/bin/bash

pip3 install pytest==8.3.4 lark==1.2.2 -q

cd /app
RESULT=0
pytest /tests/test_state.py -v || RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $RESULT
