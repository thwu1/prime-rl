#!/bin/bash

# Copy the corrected implementation
cp /solution/corrected_impl.py /app/corrected.py

# Generate the audit report by comparing reference against corrected
python3 /solution/generate_report.py
