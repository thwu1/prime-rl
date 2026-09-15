#!/bin/bash

# Reverse-engineer the firmware and compare against the spec.

echo "=== Disassembling firmware ==="
arm-none-eabi-objdump -d /app/firmware.elf

echo ""
echo "=== Analyzing firmware vs spec and computing outputs ==="
python3 /solution/compute.py
