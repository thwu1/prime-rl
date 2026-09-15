#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app

# Compile the solution into a shared library
COMPILE_OK=0
if [ -f /app/walloc_native.c ]; then
    echo "Compiling walloc_native.c..."
    gcc -shared -fPIC -O2 -DNDEBUG -Wall -I/app -o /app/libwalloc.so /app/walloc_native.c 2>&1
    if [ $? -eq 0 ]; then
        COMPILE_OK=1
        echo "Compilation succeeded."
    else
        echo "Compilation failed."
    fi
else
    echo "ERROR: /app/walloc_native.c not found"
fi

if [ "$COMPILE_OK" -ne 1 ]; then
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
python3 -m pytest /tests/test_state.py -v
TEST_RESULT=$?

mkdir -p /logs/verifier
if [ $TEST_RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_RESULT
