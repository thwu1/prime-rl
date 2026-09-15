#!/bin/bash


pip3 install pytest==8.3.4 numpy==2.1.3 -q

cd /app

# Run the full Makefile pipeline
make all 2>&1
make_exit=$?

# Run pytest
pytest /tests/test_state.py -v
pytest_exit=$?

# Determine overall result
if [ $make_exit -eq 0 ] && [ $pytest_exit -eq 0 ]; then
    exit_code=0
else
    exit_code=1
fi

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $exit_code
