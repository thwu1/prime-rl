#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app

# Run the agent's audit tool if outputs don't exist yet
if [ ! -f audit.json ] || [ ! -f audit.db ]; then
    if [ -f audit.py ]; then
        python3 audit.py
        RUN_EXIT=$?
        if [ $RUN_EXIT -ne 0 ]; then
            echo "audit.py exited with code $RUN_EXIT"
        fi
    fi
fi

# Run verification tests
pytest /tests/test_state.py -v
TEST_RESULT=$?

mkdir -p /logs/verifier
if [ $TEST_RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_RESULT
