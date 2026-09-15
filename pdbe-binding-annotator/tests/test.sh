#!/bin/bash

pip3 install pytest==8.3.4 requests==2.32.3 -q

# Run the tool with the test case
cd /app
python3 /app/binding_site_annotator.py 1cbs A 200 2>&1
TOOL_EXIT=$?

if [ $TOOL_EXIT -ne 0 ]; then
    echo "Tool exited with code $TOOL_EXIT"
fi

# Run pytest
pytest /tests/test_state.py -v 2>&1
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
