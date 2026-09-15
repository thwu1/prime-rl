#!/bin/bash

set -e

# Step 1: Assemble each .s file into .hex using the RISC-V toolchain
mkdir -p /app/programs

for src in /app/src/*.s; do
    name=$(basename "$src" .s)

    # Assemble to object file (RV32I, ILP32 ABI)
    riscv64-linux-gnu-as -march=rv32i -mabi=ilp32 -o "/tmp/${name}.o" "$src"

    # Link with the provided linker script
    riscv64-linux-gnu-ld -m elf32lriscv -T /app/link.ld -o "/tmp/${name}.elf" "/tmp/${name}.o"

    # Extract raw binary
    riscv64-linux-gnu-objcopy -O binary "/tmp/${name}.elf" "/tmp/${name}.bin"

    # Convert binary to hex word format
    python3 /solution/bin_to_hex.py "/tmp/${name}.bin" "/app/programs/${name}.hex"
done

# Step 2: Install the analyzer module
cp /solution/solver.py /app/rv32i_analyzer.py
