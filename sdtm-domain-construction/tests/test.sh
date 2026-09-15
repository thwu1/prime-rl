#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 pandas==2.2.3 pyreadstat==1.2.7 lxml==5.3.0 -q

# Run pytest and capture exit code
python3 -m pytest /tests/test_state.py -v --tb=short 2>&1
PYTEST_EXIT=$?

# Write reward based on test result
mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $PYTEST_EXIT
