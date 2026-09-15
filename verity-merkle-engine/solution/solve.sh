#!/bin/bash

# Deploy the forensic analysis tool
cp /solution/verity_forensics_impl.py /app/verity_forensics.py
chmod +x /app/verity_forensics.py

# Verify it can be imported and shows help
python3 /app/verity_forensics.py --help > /dev/null 2>&1
echo "Solution deployed to /app/verity_forensics.py"
