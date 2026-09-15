#!/bin/bash

pip3 install pytest==8.3.4 pandas==2.2.3 numpy==2.1.3 pyarrow==17.0.0 -q

cd /app
python3 /app/projector.py

EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo "projector.py failed with exit code $EXIT_CODE"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

pytest /tests/test_state.py -v
PYTEST_EXIT=$?

mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $PYTEST_EXIT
