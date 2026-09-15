#!/bin/bash

pip3 install pytest==8.3.4 hypothesis==6.100.0 redis==5.0.3 -q

redis-server --daemonize yes --save "" --appendonly no
sleep 0.5

cd /app
python3 -m pytest /tests/test_state.py -v
RESULT=$?

redis-cli shutdown nosave 2>/dev/null

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $RESULT
