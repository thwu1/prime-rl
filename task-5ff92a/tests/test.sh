#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app

# Run Makefile targets if Makefile exists
if [ -f Makefile ]; then
    make -k all static check-symbols analyze verify-prime 2>&1 || true
fi

# Fallback: compile library if Makefile didn't produce it
if [ ! -f /app/libp256mont.so ] && [ -f /app/p256_mont.c ]; then
    gcc -shared -fPIC -O2 -o /app/libp256mont.so /app/p256_mont.c 2>/tmp/compile_err.txt
    COMPILE_RC=$?
    if [ $COMPILE_RC -ne 0 ]; then
        echo "Compilation failed:"
        cat /tmp/compile_err.txt
    fi
fi

# Run tests
pytest /tests/test_state.py -v --tb=short 2>&1
TEST_RC=$?

mkdir -p /logs/verifier
if [ $TEST_RC -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_RC
