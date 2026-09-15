#!/bin/bash

set +e

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Generate test telemetry data
python3 /tests/generate_telemetry.py
GEN_EXIT=$?
if [ $GEN_EXIT -ne 0 ]; then
    echo "Test data generation failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Compile Java source
mkdir -p /app/bin
javac -d /app/bin /app/src/*.java 2>&1
COMPILE_EXIT=$?
if [ $COMPILE_EXIT -ne 0 ]; then
    echo "Java compilation failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run the pipeline
java -cp /app/bin CcsdsPipeline /app/telemetry.bin /app/output.json 2>&1
RUN_EXIT=$?
if [ $RUN_EXIT -ne 0 ]; then
    echo "Pipeline execution failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run verification tests
pytest /tests/test_state.py -v 2>&1
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
