#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

RESULTS_DIR=/tmp/flux-results
mkdir -p "$RESULTS_DIR"
chmod 777 "$RESULTS_DIR"

# Ensure fixed config is readable
chmod -R a+rX /app/fixed-config/ 2>/dev/null || true

# Start a Flux test instance with 8 brokers.
# Config is applied dynamically inside validate.sh via apply_config.py
# to avoid hostname mismatch issues in containerized environments.
flux start --test-size=8 bash /tests/validate.sh

echo "Flux validation completed with exit code: $?"

# Run pytest to check validation results
pytest /tests/test_state.py -v
exit_code=$?

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $exit_code
