#!/usr/bin/env bash

pip3 install pytest==8.3.4 -q

cd /app

# Rebuild from source to pick up any changes the agent made
make clean && make

BUILDRC=$?
if [ $BUILDRC -ne 0 ]; then
    echo "Build failed with exit code $BUILDRC"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

if [ ! -f /app/compositor ]; then
    echo "ERROR: /app/compositor binary not found after build"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

pytest /tests/test_state.py -v
EXITCODE=$?

mkdir -p /logs/verifier
if [ $EXITCODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXITCODE
