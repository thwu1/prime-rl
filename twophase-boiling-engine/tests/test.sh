#!/bin/bash

pip3 install pytest==8.3.4 -q

# Run the solver's implementation to generate results
cd /app
python3 /app/twophase.py 2>&1 || true

# Run verification tests
pytest /tests/test_state.py -v
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
