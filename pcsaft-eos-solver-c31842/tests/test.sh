#!/bin/bash

pip3 install pytest==8.3.4 -q

# Build the Rust project
cd /app
cargo build --release 2>&1
BUILD_EXIT=$?

if [ $BUILD_EXIT -ne 0 ]; then
    echo "Rust build failed with exit code $BUILD_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run the binary to produce results.json
cargo run --release 2>&1
RUN_EXIT=$?

if [ $RUN_EXIT -ne 0 ]; then
    echo "Rust binary failed with exit code $RUN_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run verification tests
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier

if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
