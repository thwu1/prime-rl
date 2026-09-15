#!/bin/bash

# Run the pipeline if output doesn't exist yet
if [ ! -f /app/output/fused.nt ]; then
    cd /app
    if [ -f /app/pipeline.py ]; then
        python3 /app/pipeline.py 2>&1 || true
    fi
fi

# Run tests
cd /app
pytest /tests/test_state.py -v
exit_code=$?

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $exit_code
