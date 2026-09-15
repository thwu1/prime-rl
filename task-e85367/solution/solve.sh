#!/bin/bash

# Install solution dependencies
pip3 install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu -q 2>/dev/null || true

# Deploy the implementation
cp /solution/impl.py /app/mla_dsa_attention.py

# Export traced model and generate profiling report
cd /app && python3 /solution/export_and_profile.py

echo "Solution deployed and artifacts generated"
