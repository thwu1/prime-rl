#!/bin/bash

set -e

python3 /solution/fix_configs.py

# Verify all configs exist after fix
for r in r1 r2 r3 r4; do
    if [ ! -f "/app/configs/$r.conf" ]; then
        echo "ERROR: /app/configs/$r.conf not found after fix"
        exit 1
    fi
done

echo "All configurations fixed and verified."
