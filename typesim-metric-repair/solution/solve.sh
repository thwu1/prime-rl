#!/bin/bash

# Install runtime dependencies
pip3 install scipy==1.13.1 numpy==1.26.4 -q

# Restore task data from backup if /app was cleared
if [ ! -f /app/test_cases.json ] && [ -d /opt/task_setup ]; then
    mkdir -p /app/typesim
    cp -r /opt/task_setup/* /app/
fi

# Deploy the designed parser and similarity modules
cp /solution/fixed_parser.py /app/typesim/parser.py
cp /solution/fixed_similarity.py /app/typesim/similarity.py

# Verify the implementation against all test cases
cd /app && python3 compute_similarity.py
