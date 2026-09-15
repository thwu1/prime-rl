#!/usr/bin/env bash

cd /app

# Step 1: Use seccomp-tools to disassemble the BPF filter for reference
echo "=== BPF Disassembly (seccomp-tools) ==="
seccomp-tools disasm /app/seccomp_filter.bpf
echo ""

# Step 2: Reverse-engineer the BPF filter into a seccomp profile
echo "=== Building original seccomp profile ==="
python3 /solution/decompile_bpf.py

# Step 3: Generate the hardened profile
echo "=== Generating hardened profile ==="
python3 /solution/harden_profile.py
