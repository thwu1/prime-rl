#!/bin/bash

# Disassemble program.bin to understand the test ROM
da65 --start-addr 0x0000 /app/program.bin > /app/disasm_full.s 2>/dev/null || true

# Run diagnostics on the buggy emulator to identify conformance failures
cp /app/program.bin /app/test_suite.bin
python3 /solution/create_diagnostics.py

# Fix all identified conformance failures in the emulator
python3 /solution/fix_emulator.py

# Verify the fixes by running the emulator on the original program
cp /app/program.bin /app/test_suite.bin
python3 /app/emulator.py
