#!/bin/bash

pip3 install pyyaml==6.0.2 -q

# Deploy the auditor
cp /solution/auditor.py /app/audit.py
chmod +x /app/audit.py

# Run the audit
cd /app
python3 /app/audit.py
