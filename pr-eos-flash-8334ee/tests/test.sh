#!/bin/bash

pip3 install pytest==8.3.4 -q

# Verify the build system produces a valid shared library
make -C /app/libcubic
MAKE_RESULT=$?
if [ $MAKE_RESULT -ne 0 ]; then
    echo "make -C /app/libcubic failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

cd /app
pytest /tests/test_state.py -v
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
