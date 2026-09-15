#!/bin/bash

set -euo pipefail

# Fix the three bugs in the TLA+ specification
python3 /solution/fix_spec.py

# Verify the fix by running TLC
cd /app
java -jar /usr/local/lib/tla2tools.jar VotingProtocol.tla -config VotingProtocol.cfg -deadlock

# Install the Python state space explorer
cp /solution/explorer_impl.py /app/explorer.py
chmod +x /app/explorer.py

# Verify the explorer matches TLC
echo "--- Explorer verification ---"
python3 /app/explorer.py --nodes 3 --values 2
echo ""
python3 /app/explorer.py --nodes 2 --values 1

# Write the bug report
python3 /solution/write_report.py
