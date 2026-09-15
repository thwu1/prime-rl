#!/bin/bash

set -e

# Install dependencies
pip3 install pyyaml==6.0.2 -q

# Copy auditor to /app/
cp /solution/auditor.py /app/nav2_auditor.py
chmod +x /app/nav2_auditor.py

# Run auditor on broken config and save report
python3 /app/nav2_auditor.py /app/nav2_params.yaml > /app/audit_report.json

echo "=== Audit report (broken config) ==="
cat /app/audit_report.json

# Generate fixed config
python3 /solution/fix_config.py /app/nav2_params.yaml /app/nav2_params_fixed.yaml

echo ""
echo "=== Auditor on fixed config ==="
python3 /app/nav2_auditor.py /app/nav2_params_fixed.yaml

echo ""
echo "Done. Created /app/nav2_auditor.py, /app/nav2_params_fixed.yaml, /app/audit_report.json"
