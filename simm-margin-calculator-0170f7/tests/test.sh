#!/bin/bash


pip3 install pytest==8.3.4 -q

# Compile Java code
cd /app
rm -rf /app/out
mkdir -p /app/out
javac -d /app/out /app/src/*.java 2>/tmp/compile_errors.txt
COMPILE_EXIT=$?

if [ $COMPILE_EXIT -ne 0 ]; then
    echo "Java compilation failed:"
    cat /tmp/compile_errors.txt
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

echo "Java compilation successful"

# Run pytest
cd /
pytest /tests/test_state.py -v
EXIT_CODE=$?

# Write reward
mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
