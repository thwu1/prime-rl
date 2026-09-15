#!/bin/bash

set +e

cd /app

# Build the solver
make clean && make
BUILD_RC=$?

if [ $BUILD_RC -ne 0 ]; then
    echo "Build failed with exit code $BUILD_RC"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run the solver with default config
./pekeris_solver
RUN_RC=$?

if [ $RUN_RC -ne 0 ]; then
    echo "Execution failed with exit code $RUN_RC"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run the test suite
pytest /tests/test_state.py -v
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
