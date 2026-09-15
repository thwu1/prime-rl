#!/bin/bash

set -u

# Install setuptools first (provides pkg_resources needed by some packages)
pip3 install setuptools==75.6.0 wheel==0.45.1 -q

# Install test dependencies separately for robustness
# gsw 3.6.19 provides pre-built binary wheels for Python 3.12 on x86_64
pip3 install numpy==2.1.3 -q
pip3 install gsw==3.6.19 -q
pip3 install pytest==8.3.4 -q

cd /app
make clean
make

if [ $? -ne 0 ]; then
    echo "Build failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Build shared library for ctypes-based anti-cheat tests
gcc -shared -fPIC -o /app/libgsw_pipeline.so /app/gsw_pipeline.c -lm 2>/dev/null

./ctd_pipeline

RESULT=$?
if [ $RESULT -ne 0 ]; then
    echo "ctd_pipeline exited with code $RESULT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

pytest /tests/test_state.py -v
TEST_RESULT=$?

mkdir -p /logs/verifier
if [ $TEST_RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_RESULT
