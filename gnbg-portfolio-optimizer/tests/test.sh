#!/bin/bash

# Default to failure
mkdir -p /logs/verifier
echo "0.0" > /logs/verifier/reward.txt

pip3 install iohgnbg==0.0.2 pytest==8.3.4 numpy==2.1.3 scipy==1.14.1 -q

python3 -m pytest /tests/test_state.py -v --tb=short 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
