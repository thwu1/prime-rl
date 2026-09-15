#!/bin/bash

pip3 install pytest==8.3.4 meshio==5.3.5 numpy==2.1.3 -q

# Run the agent's pipeline to produce output
cd /app
if [ -f /app/pipeline.py ]; then
    python3 /app/pipeline.py
elif [ -f /app/engine.py ]; then
    python3 /app/engine.py
fi

# Run verification tests
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
    exit 0
else
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi
