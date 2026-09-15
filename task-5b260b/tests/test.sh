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

pip3 install pytest==8.3.4 -q

cd /app

pytest /tests/test_state.py -v
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
  echo "1.0" > /logs/verifier/reward.txt
else
  echo "0.0" > /logs/verifier/reward.txt
fi
exit $RESULT
