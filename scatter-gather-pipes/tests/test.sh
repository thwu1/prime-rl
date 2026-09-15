#!/bin/bash

set -u

pip3 install pytest==8.3.4 -q

# Generate deterministic test data
mkdir -p /app/data
python3 -c "
import sys
sys.path.insert(0, '/tests')
from test_state import generate_log
with open('/app/data/access.log', 'w') as f:
    f.write(generate_log())
"

# Run tests
RESULT=0
python3 -m pytest /tests/test_state.py -v --tb=short || RESULT=$?

# Write reward
mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $RESULT
