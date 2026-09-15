#!/bin/bash

set -e

cd /app

# Apply cryptographic fixes to the source
python3 /solution/fix_crypto.py

# Rebuild the binary with the fixed source
make clean
make

echo "Build complete. Verifying round-trip..."

# Quick smoke test: encrypt and decrypt a small file
dd if=/dev/urandom of=/tmp/test_pt.bin bs=1024 count=1 2>/dev/null
./cryptvault keygen /tmp/test.key
./cryptvault encrypt -k /tmp/test.key /tmp/test_pt.bin /tmp/test_ct.bin
./cryptvault decrypt -k /tmp/test.key /tmp/test_ct.bin /tmp/test_dec.bin

if cmp -s /tmp/test_pt.bin /tmp/test_dec.bin; then
    echo "Round-trip OK (small file)"
else
    echo "ERROR: round-trip failed" >&2
    exit 1
fi

# Smoke test: large file
dd if=/dev/urandom of=/tmp/test_large_pt.bin bs=1024 count=128 2>/dev/null
./cryptvault encrypt -k /tmp/test.key /tmp/test_large_pt.bin /tmp/test_large_ct.bin
./cryptvault decrypt -k /tmp/test.key /tmp/test_large_ct.bin /tmp/test_large_dec.bin

if cmp -s /tmp/test_large_pt.bin /tmp/test_large_dec.bin; then
    echo "Round-trip OK (large file)"
else
    echo "ERROR: large file round-trip failed" >&2
    exit 1
fi

# Cleanup
rm -f /tmp/test_pt.bin /tmp/test_ct.bin /tmp/test_dec.bin /tmp/test.key
rm -f /tmp/test_large_pt.bin /tmp/test_large_ct.bin /tmp/test_large_dec.bin

echo "All fixes applied and verified."
