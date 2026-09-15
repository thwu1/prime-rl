#!/bin/bash

pip3 install pytest==8.3.4 redis==5.0.3 -q

# Ensure Redis is running (agent should have left it running)
redis-cli ping 2>/dev/null || { redis-server --daemonize yes --save "" 2>/dev/null; sleep 2; }

cd /app
pytest /tests/test_state.py -v
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $RESULT
