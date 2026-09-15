#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app

# Run all Go tests with a timeout
go test -count=1 -timeout 120s ./pkg/... > /tmp/test_output.txt 2>&1
GO_EXIT=$?

# Write output for pytest to read
cp /tmp/test_output.txt /tmp/go_test_result.txt
echo "EXIT_CODE=$GO_EXIT" >> /tmp/go_test_result.txt

# Run pytest verification
pytest /tests/test_state.py -v
PYTEST_EXIT=$?

mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $PYTEST_EXIT
