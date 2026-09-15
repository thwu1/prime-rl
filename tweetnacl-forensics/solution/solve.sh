#!/bin/bash

set -e

pip3 install pynacl==1.5.0 -q

cd /app

# Build both library variants
make clean && make all

# Deploy the auditor
cp /solution/nacl_auditor.py /app/nacl_auditor.py
chmod +x /app/nacl_auditor.py

# Run auditor on both builds
echo "=== Auditing reference build ==="
python3 /app/nacl_auditor.py /app/libtweetnacl_reference.so

echo ""
echo "=== Auditing suspect build ==="
python3 /app/nacl_auditor.py /app/libtweetnacl_suspect.so

echo ""
echo "Audit complete."
