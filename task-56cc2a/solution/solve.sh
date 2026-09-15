#!/bin/bash

# Step 1: Decode the microcode ROM and produce disassembly
python3 /solution/solve_rom.py

# Step 2: Install the division simulator
cp /solution/solver.py /app/simulator.py

# Step 3: Generate NASM test program, assemble, run, produce ground_truth.json
python3 /solution/solve_nasm.py
