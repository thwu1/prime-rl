#!/bin/bash


# Install dependencies
pip3 install pytest==8.3.4 -q

# Deploy the savepoint implementation
cp /solution/implement_savepoint.py /app/savepoint.py

# Verify
cd /app && python3 -m pytest /tests/test_state.py -v
