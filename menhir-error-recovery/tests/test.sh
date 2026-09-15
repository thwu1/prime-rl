#!/bin/bash

pip3 install pytest==8.3.4 -q

# Build the OCaml project
cd /app
dune build 2>&1
build_exit=$?

if [ $build_exit -ne 0 ]; then
    echo "Build failed with exit code $build_exit"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
pytest /tests/test_state.py -v
exit_code=$?

# Write reward
mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $exit_code
