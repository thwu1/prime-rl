#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Inject hidden test patients into the patient directory
if [ -d /tests/hidden_patients ]; then
    cp /tests/hidden_patients/*.json /app/patients/
fi

# Run the agent's evaluator
if [ -f /app/evaluate.py ]; then
    cd /app && python3 /app/evaluate.py
    EVAL_EXIT=$?
    if [ $EVAL_EXIT -ne 0 ]; then
        echo "Evaluator failed with exit code $EVAL_EXIT"
        mkdir -p /logs/verifier
        echo "0.0" > /logs/verifier/reward.txt
        exit 1
    fi
else
    echo "Error: /app/evaluate.py not found"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest
python3 -m pytest /tests/test_state.py -v
PYTEST_EXIT=$?

mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $PYTEST_EXIT
