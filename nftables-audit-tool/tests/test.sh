#!/bin/bash

# Run the audit tool on each config
mkdir -p /app/results
python3 /app/nft_audit.py /app/configs/workstation.conf /app/queries.json /app/results/workstation.json
RET1=$?
python3 /app/nft_audit.py /app/configs/server.conf /app/queries.json /app/results/server.json
RET2=$?
python3 /app/nft_audit.py /app/configs/router.conf /app/queries.json /app/results/router.json
RET3=$?

if [ $RET1 -ne 0 ] || [ $RET2 -ne 0 ] || [ $RET3 -ne 0 ]; then
    echo "Audit tool failed to run on one or more configs"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Verify results
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
