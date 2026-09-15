#!/bin/bash

export HOME=/root
export ELAN_HOME=/root/.elan
export PATH="/root/.elan/bin:/usr/local/bin:$PATH"

# Fallback: install elan + Lean 4 toolchain if lake is not available
if ! command -v lake &> /dev/null; then
    echo "lake not found — installing elan and Lean 4 toolchain..."
    curl -fL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -o /tmp/elan-init.sh
    bash /tmp/elan-init.sh -y --default-toolchain leanprover/lean4:v4.12.0
    rm -f /tmp/elan-init.sh
    export PATH="/root/.elan/bin:$PATH"
    echo "Lean 4 installed: $(lean --version)"
fi

# Generate the fixed and proven Lean file
# This script:
# 1. Removes the misleading 'attribute [irreducible] myReverse' line
# 2. Removes the artificially low 'set_option maxHeartbeats 4000' limit
# 3. Fixes filter_length statement from = to ≤
# 4. Replaces all sorry placeholders with valid proofs
python3 /solution/proven_ops.py

# Build to verify proofs compile
cd /app
lake build
