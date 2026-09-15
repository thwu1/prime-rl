#!/bin/bash

pip3 install pytest==8.3.4 -q

# Ensure build environment files are present at /app (restore from backup
# if the base image content was not properly overwritten during Docker build)
mkdir -p /app/include /app/src
for f in Makefile src/stress_test.cpp src/benchmark.cpp; do
    if [ -f "/opt/task_env/$f" ]; then
        cp -f "/opt/task_env/$f" "/app/$f"
    fi
done

cd /app

pytest_exit=0
python3 -m pytest /tests/test_state.py -v --tb=short || pytest_exit=$?

mkdir -p /logs/verifier
if [ "$pytest_exit" -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $pytest_exit
