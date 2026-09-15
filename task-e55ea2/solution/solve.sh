#!/bin/bash

# Deploy the tax engine to the application directory
cp /solution/tax_engine.pl /app/tax_engine.pl

# Verify correctness by running all 12 cases through SWI-Prolog
pip3 install pytest==8.3.4 -q

python3 /solution/verify.py
