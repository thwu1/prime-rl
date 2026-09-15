#!/bin/bash

# Install test dependencies
python3 -m pip install pytest==8.3.4 numpy==2.1.3 -q

cd /app

# Run the agent's co-simulation master
python3 /app/cosim_master.py
run_exit=$?

if [ $run_exit -ne 0 ]; then
    echo "cosim_master.py execution failed with exit code $run_exit"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run verification tests
python3 -m pytest /tests/test_state.py -v
test_exit=$?

mkdir -p /logs/verifier
if [ $test_exit -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $test_exit
