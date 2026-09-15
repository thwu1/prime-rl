#!/bin/bash

# Install TypeScript
npm install -g typescript@5.7.3 2>/dev/null

echo "=== Applying fixes ==="
python3 /solution/fix_config.py
FIX_EXIT=$?

if [ $FIX_EXIT -ne 0 ]; then
    echo "Fix script failed with exit code $FIX_EXIT" >&2
    exit 1
fi

echo "=== Building library ==="
cd /app/lib && rm -rf dist && tsc -p tsconfig.json
LIB_EXIT=$?
if [ $LIB_EXIT -ne 0 ]; then
    echo "Library compilation failed" >&2
    exit 1
fi

echo "=== Building consumer ==="
cd /app/consumer && rm -rf dist && tsc -p tsconfig.json
CON_EXIT=$?
if [ $CON_EXIT -ne 0 ]; then
    echo "Consumer compilation failed" >&2
    exit 1
fi

echo ""
echo "=== Verification ==="
node /app/consumer/dist/main.js
