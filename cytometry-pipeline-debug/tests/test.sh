#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 numpy==2.1.3 scipy==1.14.1 -q

# Generate the synthetic FCS test file
python3 /tests/generate_fcs.py

# Run the pipeline
cd /app
Rscript pipeline.R /app/data/test_sample.fcs /app/output/ 2>&1
PIPELINE_EXIT=$?

if [ $PIPELINE_EXIT -ne 0 ]; then
    echo "Pipeline failed with exit code $PIPELINE_EXIT"
fi

# Run pytest verification
python3 -m pytest /tests/test_state.py -v 2>&1
TEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
