#!/bin/bash

# Kill any running server from a previous attempt
pkill -f '/app/server' 2>/dev/null || true
sleep 0.3

# Compile the server
cd /app
make clean && make
if [ $? -ne 0 ]; then
    echo "Compilation failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Install test deps
pip3 install pytest==8.3.4 -q

# Run tests
cd /tests
pytest test_state.py -v
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $RESULT
