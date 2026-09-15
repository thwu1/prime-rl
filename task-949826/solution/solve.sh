#!/bin/bash

# Deploy the audit tool
cp /solution/ptw_audit_impl.py /app/ptw_audit
chmod +x /app/ptw_audit

# Verify against the sample output
echo "=== Running audit tool ==="
python3 /app/ptw_audit
