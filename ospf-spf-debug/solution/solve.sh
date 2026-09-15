#!/usr/bin/env bash


set -euo pipefail

# Apply the three targeted fixes to the OSPF SPF calculator
python3 /solution/fix_bugs.py

# Verify the patched calculator produces correct routing table
python3 /app/ospf_spf.py /app/topology.json
