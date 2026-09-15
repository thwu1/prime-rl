#!/bin/bash

set -euo pipefail

python3 /solution/fix_arith.py

# Verify the fix was applied
if ! bash /app/arith.sh to_base 64 36 | grep -q '^A$'; then
    echo "ERROR: val_to_char fix not applied" >&2
    exit 1
fi
if ! bash /app/arith.sh to_base 16 0 | grep -q '^0$'; then
    echo "ERROR: to_base zero fix not applied" >&2
    exit 1
fi
if ! bash /app/arith.sh fp_add 1.5 1.5 2 | grep -q '^3\.00$'; then
    echo "ERROR: fp_parse padding fix not applied" >&2
    exit 1
fi
if ! bash /app/arith.sh sanitize '-019' | grep -q '^-19$'; then
    echo "ERROR: sanitize fix not applied" >&2
    exit 1
fi

echo "All fixes verified."
