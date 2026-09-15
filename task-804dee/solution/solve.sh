#!/bin/bash

pip3 install pyyaml==6.0.2 -q

# Step 1: Deploy the configuration auditor
cp /solution/auditor_impl.py /app/auditor.py
chmod +x /app/auditor.py

# Step 2: Fix all configuration defects
python3 /solution/fix_configs.py

# Step 3: Verify — original configs should fail, fixed configs should pass
echo ""
echo "=== Verifying: auditor against original (backup) configs ==="
python3 /app/auditor.py /app/containers_backup/ && {
    echo "ERROR: original configs should have failed audit"
    exit 1
} || echo "(Expected non-zero — original configs have defects)"

echo ""
echo "=== Verifying: auditor against fixed configs ==="
python3 /app/auditor.py /app/containers/
