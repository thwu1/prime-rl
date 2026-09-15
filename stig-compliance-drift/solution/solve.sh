#!/bin/bash

cd /app

# Remediate all 8 controls and generate remediation report
python3 /solution/remediate.py

# Create and install the compliance validator
cp /solution/validator_code.py /app/validator.py

# Run the validator to verify all controls pass and generate results
python3 /app/validator.py

# Generate risk assessment
python3 /solution/create_risk_assessment.py
