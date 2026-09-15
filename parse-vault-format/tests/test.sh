#!/bin/bash

# Run the agent's parser on the main vault
if [ -f /app/vault_parser.py ]; then
    python3 /app/vault_parser.py /app/archive.vault /app/results 2>/dev/null || true
fi

# Run the agent's parser on the extra test vault
if [ -f /app/vault_parser.py ]; then
    python3 /app/vault_parser.py /app/test_extra.vault /app/results_extra 2>/dev/null || true
fi

# Run pytest
pytest /tests/test_state.py -v
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $RESULT
