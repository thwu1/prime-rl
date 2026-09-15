#!/bin/bash

# Clean previous results
rm -f /app/results/report.json
rm -rf /app/results/schemathesis_output

# Start fresh API server from compiled bytecode
cd /app
python3 /app/start_server.py &
SERVER_PID=$!
sleep 3

# Verify server is up
for i in 1 2 3 4 5; do
    if curl -sf http://localhost:5000/api/v1/health > /dev/null 2>&1; then
        break
    fi
    sleep 2
done

if ! curl -sf http://localhost:5000/api/v1/health > /dev/null 2>&1; then
    echo "ERROR: API server failed to start"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run the agent's fuzzer
if [ ! -f /app/run_fuzzer.sh ]; then
    echo "ERROR: /app/run_fuzzer.sh not found"
    kill $SERVER_PID 2>/dev/null
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

chmod +x /app/run_fuzzer.sh
timeout 240 /app/run_fuzzer.sh http://localhost:5000
FUZZER_EXIT=$?

# Stop server
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null

# Install test dependencies AFTER fuzzer completes to avoid breaking schemathesis
pip3 install pytest==7.4.4 -q

# Run verification tests
python3 -m pytest /tests/test_state.py -v
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
