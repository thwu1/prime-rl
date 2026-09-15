#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Wait for named to be responsive (up to 30 seconds)
echo "Waiting for named to respond..."
for i in $(seq 1 15); do
    dig @127.0.0.1 weilburg.corp SOA +timeout=2 +tries=1 &>/dev/null && break
    sleep 2
done

# Wait for DNSSEC signing to complete (up to 120 seconds)
echo "Waiting for DNSSEC signing to complete..."
for i in $(seq 1 40); do
    result=$(dig @127.0.0.1 weilburg.corp DNSKEY +short +timeout=3 2>/dev/null)
    if [ -n "$result" ]; then
        echo "DNSSEC signing detected"
        # Extra wait for all RRSIGs to be generated
        sleep 5
        break
    fi
    sleep 3
done

# Run pytest and capture exit code
pytest /tests/test_state.py -v
EXIT_CODE=$?

# Write reward based on test outcome
mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
