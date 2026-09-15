#!/bin/bash

# Copy the fixed proof manager into place and run it
cp /solution/proof_mgr_fixed.py /app/proof_mgr.py
cd /app
python3 /app/proof_mgr.py
