#!/bin/bash

# Clean prior outputs to verify from a clean slate
rm -rf /app/output /app/calibrated

# Re-run the agent's fixed pipeline
cd /app
bash /app/run_pipeline.sh || true

# Verify results
cd /
python3 -m pytest /tests/test_state.py -v
test_exit=$?

mkdir -p /logs/verifier
if [ $test_exit -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $test_exit
