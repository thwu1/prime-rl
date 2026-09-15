#!/bin/bash

# Ensure Rust/Verus env is available
export CARGO_HOME=/opt/cargo
export RUSTUP_HOME=/opt/rustup
export PATH="/opt/verus:/opt/cargo/bin:/usr/local/bin:$PATH"

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Run pytest on the test file
pytest /tests/test_state.py -v
TEST_EXIT=$?

# Write reward based on test result
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
