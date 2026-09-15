#!/bin/bash

pip3 install pytest==8.3.4 -q

# Run the reference processor to generate fresh output (anti-cheat: verifies
# processor code, not hand-crafted output files)
python3 /app/processor.py \
  --bundle /app/data/transaction_bundle.json \
  --state-dir /app/data/server_state \
  --output-dir /app/output \
  --base-url http://fhir.example.org 2>&1 || true

PYTEST_EXIT=0
cd /app
python3 -m pytest /tests/test_state.py -v --tb=short 2>&1 || PYTEST_EXIT=$?

mkdir -p /logs/verifier
if [ "$PYTEST_EXIT" -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $PYTEST_EXIT
