#!/bin/bash

# Install the corrected source files with all bug fixes and enhancements
cp /solution/sesrec_fixed.c /app/src/sesrec.c
cp /solution/sesplay_fixed.c /app/src/sesplay.c

# Build
cd /app && make clean && make

echo "Build completed. Verifying fixes and features..."

# Test v1 format timing accuracy
echo "--- V1 format test ---"
./sesrec -q -f v1 -o /tmp/verify_v1_ts -T /tmp/verify_v1_tm -c "echo -n A; sleep 2; echo -n B"
echo "V1 timing data:"
cat /tmp/verify_v1_tm

# Test v2 format (default)
echo ""
echo "--- V2 format test (default) ---"
./sesrec -q -o /tmp/verify_v2_ts -T /tmp/verify_v2_tm -c "echo -n A; sleep 2; echo -n B"
echo "V2 timing data:"
cat /tmp/verify_v2_tm

# Test analyze mode on both formats
echo ""
echo "--- Analyze v1 ---"
./sesplay --analyze -T /tmp/verify_v1_tm

echo ""
echo "--- Analyze v2 ---"
./sesplay --analyze -T /tmp/verify_v2_tm

# Test replay
echo ""
echo "--- Replay v2 ---"
./sesplay -T /tmp/verify_v2_tm /tmp/verify_v2_ts
echo ""
echo "All verifications complete."
