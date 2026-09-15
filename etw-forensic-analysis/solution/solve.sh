#!/usr/bin/env bash

# Solution: Parse the ETW memory dump, perform comparative technique
# evaluation for both bypass sessions, and create a YARA detection rule.

cd /app

# Step 1: Use radare2 to explore binary structure and discover Flags offset.
# Search for NT Kernel Logger's expected flags pattern (0x28 = KernelTrace|RealTime)
# within the first session entry to locate the Flags field offset.
echo "=== Binary exploration with radare2 ==="
r2 -q -e scr.color=0 -c "
px 64 @ 0
s 0x40
/x 28000000
" etw_dump.bin 2>/dev/null || true

# Step 2: Run full analysis — forensic identification, comparative
# technique evaluation, YARA generation
python3 /solution/analyze_dump.py

# Step 3: Validate YARA rule with yara CLI against both dumps
echo ""
echo "=== YARA rule validation ==="
echo "Attack dump:"
yara /app/detect_bypass.yar /app/etw_dump.bin
echo "Clean reference dump:"
yara /app/detect_bypass.yar /app/etw_clean.bin || echo "(no match — expected for clean dump)"
