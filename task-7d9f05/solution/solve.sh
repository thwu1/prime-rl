#!/bin/bash

cd /app

echo "=== Disassembling target.o ==="
objdump -d /app/target.o

echo ""
echo "=== Compiling initial candidate ==="
gcc -c -O0 -fno-stack-protector -fno-pic -fcf-protection=none -std=c11 \
    -o /app/candidate.o /app/candidate.c 2>&1

echo ""
echo "=== Disassembling initial candidate.o ==="
objdump -d /app/candidate.o

echo ""
echo "=== Applying codegen transformations ==="
python3 /solution/solve_helper.py
