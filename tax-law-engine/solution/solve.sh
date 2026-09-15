#!/bin/bash

# Install solution dependencies
pip3 install z3-solver==4.13.4.0 -q

# Deploy the computation engine
cp /solution/tax_engine_solution.py /app/tax_engine.py

# Deploy and run formal verification
cp /solution/formal_verify_solution.py /app/formal_verify.py
cd /app
python3 /app/formal_verify.py

# Verify outputs exist
if [ ! -f /app/verification_results.json ]; then
    echo "ERROR: verification_results.json not created"
    exit 1
fi

echo "Solution deployed and verified successfully."
