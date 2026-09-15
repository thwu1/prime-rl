#!/bin/bash

# Install the corrected validator
cp /solution/glsl_link_validator_fixed.py /app/glsl_link_validator.py

# Fix incorrect manifest entries
python3 /solution/fix_manifest.py

# Generate the diagnostic report
python3 /solution/generate_report.py

# Verify
python3 /app/run_tests.py
