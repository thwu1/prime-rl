#!/bin/bash

set -u

pip3 install pytest==8.3.4 -q

# Compile with Maven and copy dependencies
cd /app
mvn -q compile dependency:copy-dependencies -DoutputDirectory=target/lib 2>&1
COMPILE_RC=$?

if [ $COMPILE_RC -ne 0 ]; then
    echo "Maven compilation failed with exit code $COMPILE_RC"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run the tests
cd /
python3 -m pytest /tests/test_state.py -v 2>&1
TEST_RC=$?

mkdir -p /logs/verifier
if [ $TEST_RC -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_RC
