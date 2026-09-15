#!/usr/bin/env python3
"""
Fix the two defects in /app/src/bcdump.c so it correctly disassembles
BCVF bytecode files per the opcode specification in opcode_def.h.

"""

SRC = "/app/src/bcdump.c"

with open(SRC, "r") as f:
    code = f.read()

# ---- Bug 1: u16 operand bytes read in wrong order (big-endian) ----
# Size-3 instructions have little-endian u16 operands:
#   byte[pc+1] is low byte, byte[pc+2] is high byte.
# The skeleton reads them as big-endian (high << 8 | low).
code = code.replace(
    '(uint16_t)((uint16_t)code[pc + 1] << 8 | code[pc + 2])',
    '(uint16_t)(code[pc + 1] | (uint16_t)code[pc + 2] << 8)',
    1,
)

# ---- Bug 2: branch target is raw relative offset, not resolved address ----
# Branch offsets are relative to the branch instruction's own start address,
# so the absolute target is pc + operand, not just operand.
code = code.replace(
    'int target = operand;',
    'int target = (int)pc + operand;',
    1,
)

with open(SRC, "w") as f:
    f.write(code)

print("bcdump.c patched successfully")
