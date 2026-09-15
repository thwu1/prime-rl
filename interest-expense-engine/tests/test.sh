#!/bin/bash

pip3 install pytest==8.3.4 -q

# Run the computation pipeline via Makefile
make -C /app all
MAKE_EXIT=$?

if [ $MAKE_EXIT -ne 0 ]; then
    echo "make all failed with exit code $MAKE_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run the report generation pipeline (sqlite3 + jq)
make -C /app report
REPORT_EXIT=$?

if [ $REPORT_EXIT -ne 0 ]; then
    echo "make report failed with exit code $REPORT_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest
pytest /tests/test_state.py -v
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_EXIT
