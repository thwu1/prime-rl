#!/bin/bash

# Part 1: Forensic analysis
cp /solution/verity_forensics.py /app/verity_forensics.py
python3 /app/verity_forensics.py

# Part 2: Generate and run remediation script
python3 /solution/gen_remediate.py
bash /app/remediate.sh
