#!/bin/bash

set -euo pipefail

# Install tools needed for fixing and verification
pip3 install pytest==8.3.4 ruff==0.4.4 mypy==1.10.0 pyyaml==6.0.2 types-PyYAML==6.0.12.20240917 -q

# Apply all fixes via the helper script
python3 /solution/fix_bugs.py

# Install the fixed package
pip3 install -e /app/ -q

# Verify all CI stages pass
echo "=== Verification ==="
cd /app

echo "--- Stage 1: pip install ---"
pip3 install -e . -q
echo "PASS"

echo "--- Stage 2: ruff check ---"
ruff check src/
echo "PASS"

echo "--- Stage 3: mypy ---"
mypy src/logminer/
echo "PASS"

echo "--- Stage 4: pytest ---"
pytest tests/ -v
echo "PASS"

echo "--- make ci ---"
make ci
echo "PASS"

echo "=== All fixes verified ==="
