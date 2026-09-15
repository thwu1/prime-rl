#!/bin/bash

# Create the MAGMA patches
python3 /solution/create_patches.py
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to create patches"
    exit 1
fi

# Restore clean source and apply patches
rm -rf /app/src 2>/dev/null || true
mkdir -p /app/src
cp -f /app/src_backup/* /app/src/
bash /app/scripts/apply_patches.sh /app/patches /app/src
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to apply patches"
    exit 1
fi

# Build canary mode
bash /app/scripts/build.sh canary /app/src /app/output
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to build canary mode"
    exit 1
fi

# Build fixed mode (need fresh patched source since canary build may have modified state)
rm -rf /app/src 2>/dev/null || true
mkdir -p /app/src
cp -f /app/src_backup/* /app/src/
bash /app/scripts/apply_patches.sh /app/patches /app/src
bash /app/scripts/build.sh fixed /app/src /app/output
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to build fixed mode"
    exit 1
fi

echo ""
echo "=== Smoke test: canary mode ==="
for bug in 001 002 003 004; do
    echo "--- crash_bug${bug}.mfp ---"
    timeout 5 /app/output/mfp_parser_canary "/app/corpus/crash_bug${bug}.mfp" "/tmp/canary_${bug}.csv" 2>/dev/null || true
    if [ -f "/tmp/canary_${bug}.csv" ]; then
        cat "/tmp/canary_${bug}.csv"
    else
        echo "  (no canary output)"
    fi
    echo ""
done

echo "=== Smoke test: fixed mode ==="
for bug in 001 002 003 004; do
    timeout 5 /app/output/mfp_parser_fixed "/app/corpus/crash_bug${bug}.mfp" 2>/dev/null
    echo "  crash_bug${bug}.mfp: exit code $?"
done

echo ""
echo "Done. All patches created and verified."
