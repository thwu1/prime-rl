#!/bin/bash

pip3 install pytest==8.3.4 -q

# Compile the Java code from /app/src
mkdir -p /app/build
JAVA_FILES=$(find /app/src -name "*.java" 2>/dev/null)
if [ -z "$JAVA_FILES" ]; then
    echo "No Java source files found in /app/src"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Build classpath from lib jars if any exist
CLASSPATH=""
if ls /app/lib/*.jar 1>/dev/null 2>&1; then
    CLASSPATH="/app/lib/*"
fi

if [ -n "$CLASSPATH" ]; then
    javac -cp "$CLASSPATH" -d /app/build $JAVA_FILES 2>/tmp/compile_errors.txt
else
    javac -d /app/build $JAVA_FILES 2>/tmp/compile_errors.txt
fi

COMPILE_EXIT=$?
if [ $COMPILE_EXIT -ne 0 ]; then
    echo "Compilation failed:"
    cat /tmp/compile_errors.txt
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest
pytest /tests/test_state.py -v
PYTEST_EXIT=$?

mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $PYTEST_EXIT
