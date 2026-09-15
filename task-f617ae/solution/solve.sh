#!/bin/bash

# The compiler was derived by reverse-engineering /app/vm_runner with radare2
# to recover the 27-opcode ISA, then disassembling /app/reference.bc with xxd
# and the recovered ISA to reconstruct the key validation algorithm.

cp /solution/compiler.py /app/compiler.py
python3 /app/compiler.py
