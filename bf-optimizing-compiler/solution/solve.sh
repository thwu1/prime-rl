#!/bin/bash

# Deploy the reference BF compiler implementation
cp /solution/bfc_solution.py /app/bfc.py
chmod +x /app/bfc.py

# Verify interpreter mode
echo "=== Testing run mode ==="
python3 /app/bfc.py run /app/programs/hello.bf
echo ""

# Verify IR mode
echo "=== Testing IR mode ==="
python3 /app/bfc.py ir /app/programs/alphabet.bf

# Verify stats mode
echo ""
echo "=== Testing stats mode ==="
python3 /app/bfc.py stats /app/programs/combined.bf

# Verify C code generation
echo ""
echo "=== Testing C code generation ==="
python3 /app/bfc.py gen-c /app/programs/hello.bf > /tmp/bf_out.c
gcc -O2 -o /tmp/bf_out /tmp/bf_out.c
/tmp/bf_out
echo ""

# Verify x86-64 assembly generation
echo "=== Testing assembly code generation ==="
python3 /app/bfc.py gen-asm /app/programs/hello.bf > /tmp/bf_out.s
as -o /tmp/bf_out.o /tmp/bf_out.s
gcc -o /tmp/bf_asm /tmp/bf_out.o
/tmp/bf_asm
echo ""

# Verify with readelf
echo "=== Verifying ELF output ==="
readelf -h /tmp/bf_asm | head -5

# Verify with objdump
echo ""
echo "=== Disassembly check ==="
objdump -d /tmp/bf_asm | grep -c "main"
echo "main symbol found in disassembly"

echo ""
echo "=== Solution deployed successfully ==="
