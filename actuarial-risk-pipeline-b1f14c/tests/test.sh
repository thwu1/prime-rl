#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q
Rscript -e 'install.packages("actuar", repos="https://cloud.r-project.org", quiet=TRUE)'

# Generate golden reference values using actuar
Rscript /tests/generate_golden.R
GOLDEN_EXIT=$?
if [ $GOLDEN_EXIT -ne 0 ]; then
    echo "Failed to generate golden values"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run solver's implementation
cd /app
Rscript /app/run_pipeline.R
SOLVER_EXIT=$?
if [ $SOLVER_EXIT -ne 0 ]; then
    echo "Solver code failed with exit code $SOLVER_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
pytest /tests/test_state.py -v
TEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_EXIT
