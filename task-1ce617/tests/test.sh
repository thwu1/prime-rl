#!/bin/bash

pip3 install pytest==8.3.4 -q

# Build the server
make -C /app/src clean && make -C /app/src
build_result=$?

if [ $build_result -ne 0 ]; then
    echo "Build failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
pytest /tests/test_state.py -v
test_result=$?

mkdir -p /logs/verifier
if [ $test_result -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $test_result
