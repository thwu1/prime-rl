#!/bin/bash

pip3 install pytest==8.3.4 requests==2.32.3 -q

TS="/usr/local/bin/typesense-server"

# Ensure Typesense is running
if ! curl -sf http://localhost:8108/health > /dev/null 2>&1; then
    echo "Typesense not running, attempting to start..."
    mkdir -p /app/typesense-data
    "$TS" --data-dir=/app/typesense-data --api-key=typesense_bench_admin_key --enable-cors > /tmp/typesense_test.log 2>&1 &
    disown
    for i in $(seq 1 60); do
        if curl -sf http://localhost:8108/health > /dev/null 2>&1; then
            echo "Typesense ready after ${i}s."
            break
        fi
        sleep 1
    done
fi

if ! curl -sf http://localhost:8108/health > /dev/null 2>&1; then
    echo "ERROR: Typesense not available"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

pytest /tests/test_state.py -v
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
