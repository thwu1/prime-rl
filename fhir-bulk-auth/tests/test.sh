#!/bin/bash

# Restore task data from durable backup if /app/ was mounted as a volume
if [ ! -f /app/config/instance.json ]; then
    mkdir -p /app/config /app/data /app/spec
    cp -r /opt/task-data/config/. /app/config/
    cp -r /opt/task-data/data/. /app/data/
    cp -r /opt/task-data/spec/. /app/spec/
fi

cd /app
pytest /tests/test_state.py -v --tb=short
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
