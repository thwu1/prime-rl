#!/bin/bash

pip3 install pytest==8.3.4 -q

# Compile Java sources and test runner
cd /app
mkdir -p build
javac -d build src/*.java /tests/TestRunner.java 2>/tests/compile_errors.txt
COMPILE_EXIT=$?

if [ $COMPILE_EXIT -ne 0 ]; then
    echo "COMPILATION FAILED"
    cat /tests/compile_errors.txt
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run Java test suite
java -cp build TestRunner > /tests/test_output.txt 2>&1
JAVA_EXIT=$?

echo "=== Java Test Output ==="
cat /tests/test_output.txt
echo "========================"

# Run pytest to verify results
RESULT=$(pytest /tests/test_state.py -v 2>&1)
PYTEST_EXIT=$?
echo "$RESULT"

if [ $PYTEST_EXIT -eq 0 ]; then
    mkdir -p /logs/verifier
    echo "1.0" > /logs/verifier/reward.txt
else
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $PYTEST_EXIT
