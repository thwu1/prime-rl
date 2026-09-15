#!/bin/bash

# Verify config file exists before attempting to start Flux
if [ ! -f /app/flux_config/system.toml ]; then
    echo "ERROR: Configuration file /app/flux_config/system.toml not found"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest inside a Flux instance using the agent's configuration.
flux start --test-size=8 --test-hosts=test[0-7]  --config-path=/app/flux_config  -- python3 -m pytest /tests/test_state.py -v --tb=short 2>&1
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
