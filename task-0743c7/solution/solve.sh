#!/bin/bash

pip3 install lxml==5.3.0 -q

# Step 1: Replace the buggy validator with the fixed version
cp /solution/fixed_validator.py /app/validator.py

# Step 2: Run the fixed validator to produce the conformance report
python3 /app/validator.py

# Step 3: Produce the remediated clinical document
python3 /solution/remediate.py
