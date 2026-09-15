#!/usr/bin/env bash

# Step 1: Analyze the stripped VM binary using binary RE tools
echo "=== Step 1: Reverse-engineering VM binary ==="
echo "Disassembling /app/vm with objdump..."
objdump -d /app/vm > /tmp/vm_disasm.txt 2>&1
echo "VM disassembly: $(wc -l < /tmp/vm_disasm.txt) lines saved to /tmp/vm_disasm.txt"

echo "Checking strings in binary..."
strings /app/vm | grep -i "opcode\|usage\|program\|unknown" || true

echo "Checking binary type..."
readelf -h /app/vm 2>/dev/null | head -5

# Step 2: Inspect candidate bytecodes
echo ""
echo "=== Step 2: Inspecting candidate bytecodes ==="
for f in /app/candidates/*.bin; do
    echo "$(basename "$f"): $(wc -c < "$f") bytes"
    xxd "$f" | head -3
    echo "..."
done

# Step 3: Run decryption and comparative analysis
echo ""
echo "=== Step 3: Running comparative analysis and decryption ==="
python3 /solution/decrypt.py
