#!/bin/bash

set -euo pipefail

# Apply the codec fix and TAG_PACKED implementation
python3 /solution/fix_codec.py

# Rebuild and verify
cd /app
make clean all
echo "=== Verifying fix ==="
./ppn_test
