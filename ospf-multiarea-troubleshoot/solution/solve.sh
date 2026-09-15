#!/bin/bash

# Design and implement all OSPF configurations from scratch by reading
# the topology spec and computing the correct FRR config for each router.

python3 /solution/design_ospf.py

echo ""
echo "=== Validation ==="
python3 /app/ospf_checker.py
