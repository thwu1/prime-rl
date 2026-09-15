#!/bin/bash

pip3 install numpy==2.1.3 pytest==8.3.4 -q

# Run the pipeline to produce output from current code state
cd /app && python3 -m pipeline.main

pytest /tests/test_state.py -v
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
