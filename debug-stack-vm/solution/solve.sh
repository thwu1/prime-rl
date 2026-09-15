#!/bin/bash

set -euo pipefail

cd /app

# Step 1: Apply bug fixes to assembler and emulator
python3 /solution/apply_fixes.py

# Step 2: Rebuild the emulator with fixes
rm -f emulator
make all

# Step 3: Install the semantics report
cp /solution/semantics_report.json /app/semantics_report.json

# Step 4: Install the disassembler
cp /solution/disassembler.py /app/disassembler.py

# Step 5: Install the optimizer
cp /solution/optimizer.py /app/optimizer.py

# Step 6: Install the selftest program
cp /solution/selftest.asm /app/programs/selftest.asm

# Step 7: Assemble the selftest
python3 /app/assembler.py /app/programs/selftest.asm /app/programs/selftest.bin

# Step 8: Verify all programs produce correct output
echo "=== Verifying programs ==="
for prog in hello fibonacci signed_ops gcd selftest; do
    actual=$(/app/emulator /app/programs/${prog}.bin)
    expected=$(cat /app/expected/${prog}.txt)
    if [ "$actual" = "$expected" ]; then
        echo "PASS: $prog"
    else
        echo "FAIL: $prog"
        echo "Expected: $expected"
        echo "Got: $actual"
        exit 1
    fi
done

# Step 9: Verify round-trip for all programs
echo "=== Verifying round-trips ==="
for prog in hello fibonacci signed_ops gcd; do
    python3 /app/disassembler.py /app/programs/${prog}.bin /tmp/rt_${prog}.asm
    python3 /app/assembler.py /tmp/rt_${prog}.asm /tmp/rt_${prog}.bin
    actual=$(/app/emulator /tmp/rt_${prog}.bin)
    expected=$(cat /app/expected/${prog}.txt)
    if [ "$actual" = "$expected" ]; then
        echo "PASS: round-trip $prog"
    else
        echo "FAIL: round-trip $prog"
        exit 1
    fi
done

# Step 10: Verify optimizer preserves semantics
echo "=== Verifying optimizer ==="
for prog in hello fibonacci signed_ops gcd; do
    python3 /app/optimizer.py /app/programs/${prog}.bin /tmp/opt_${prog}.bin
    actual=$(/app/emulator /tmp/opt_${prog}.bin)
    expected=$(cat /app/expected/${prog}.txt)
    if [ "$actual" = "$expected" ]; then
        echo "PASS: optimizer $prog"
    else
        echo "FAIL: optimizer $prog"
        exit 1
    fi
done

echo "=== All verifications passed ==="
