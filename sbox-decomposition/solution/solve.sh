#!/bin/bash

cd /app

# Step 1: Analyze the stripped ELF binary structure
echo "=== Analyzing binary sections ==="
readelf -S /app/sbox_engine > /app/section_layout.txt 2>&1
cat /app/section_layout.txt

# Step 2: Dump the .rodata section using objdump
echo "=== Dumping .rodata section ==="
objdump -s -j .rodata /app/sbox_engine > /app/rodata_dump.txt 2>&1

# Step 3: Cross-reference with hex dump for byte-level inspection
echo "=== Generating hex dump ==="
xxd /app/sbox_engine > /app/full_hexdump.txt 2>&1

# Step 4: Extract S-box from binary, perform decomposition, write answer.json
echo "=== Running S-box extraction and algebraic decomposition ==="
python3 /solution/decompose.py
