#!/bin/bash

set -u

pip3 install pytest==8.3.4 pyarrow==17.0.0 -q

# Build the Rust binary (cargo caches — fast if unchanged)
cd /app/arrow_ipc_reader && cargo build --release 2>&1 || true
cd /app

# Run tests
EXITCODE=0
python3 -m pytest /tests/test_state.py -v --tb=short 2>&1 || EXITCODE=$?

mkdir -p /logs/verifier
if [ $EXITCODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXITCODE
