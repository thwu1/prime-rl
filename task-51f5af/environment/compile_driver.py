#!/usr/bin/env python3
"""Compilation driver: allocate registers and emit x86-64 assembly.

Usage: python3 compile_driver.py <program_name> <output.s>

"""

import sys
import copy

from programs import ALL_PROGRAMS
from allocator import allocate_registers
from codegen import emit_x86

if len(sys.argv) != 3:
    print(f"Usage: {sys.argv[0]} <program_name> <output.s>", file=sys.stderr)
    sys.exit(1)

name = sys.argv[1]
outfile = sys.argv[2]

prog_dict = dict(ALL_PROGRAMS)
if name not in prog_dict:
    print(f"Unknown program: {name}", file=sys.stderr)
    print(f"Available: {', '.join(n for n, _ in ALL_PROGRAMS)}", file=sys.stderr)
    sys.exit(1)

prog = copy.deepcopy(prog_dict[name])
allocated = allocate_registers(prog)
asm_text = emit_x86(allocated)

with open(outfile, 'w') as f:
    f.write(asm_text)
