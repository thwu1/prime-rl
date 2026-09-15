#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app

if [ ! -f /app/report.json ]; then
    echo "report.json not found at /app/report.json"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

if [ ! -f /app/merged.pcap ]; then
    echo "merged.pcap not found at /app/merged.pcap"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

pytest /tests/test_state.py -v
TEST_RESULT=$?

mkdir -p /logs/verifier
if [ $TEST_RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_RESULT
