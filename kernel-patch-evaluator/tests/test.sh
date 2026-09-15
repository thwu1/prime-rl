#!/bin/bash

pip3 install pytest==8.3.4 -q

# Generate dynamic test case (anti-cheat: evaluator must work generically)
python3 /tests/gen_dynamic.py

# Run the evaluator
python3 /app/evaluator.py /app/data/cases /app/output/results.json
EVAL_EXIT=$?

# Run pytest
pytest /tests/test_state.py -v
TEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $EVAL_EXIT -eq 0 ] && [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
