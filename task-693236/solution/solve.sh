#!/bin/bash

export PYTHONPATH=/app:/opt/task_lib

pip3 install pytest==8.3.4 -q

# Deploy the reference solution
cp /solution/solution.py /app/allocator.py

cd /app
python3 -m pytest /tests/test_state.py -v --tb=short
