#!/usr/bin/env python3
"""
Fix the three bugs in the AES-128 Verilog encryption module.

Bug 1 - GF(2^8) xtime uses wrong irreducible polynomial reduction byte:
  0x1d (x^4+x^3+x^2+1) instead of 0x1b (x^4+x^3+x+1)

Bug 2 - ShiftRows row 3 circular left-shifts by 1 instead of 3:
  Byte assignments s7/s11/s15/s3 instead of s15/s3/s7/s11

Bug 3 - Key expansion RotWord rotates right instead of left:
  {sbox(w3[7:0]), sbox(w3[31:24]), ...} instead of
  {sbox(w3[23:16]), sbox(w3[15:8]), ...}
"""

with open("/app/aes128.v", "r") as f:
    code = f.read()

# Bug 1: Wrong reduction polynomial in xtime
# 0x1d should be 0x1b for AES (x^8 + x^4 + x^3 + x + 1)
code = code.replace(
    "8'h1d & {8{b[7]}}",
    "8'h1b & {8{b[7]}}"
)

# Bug 2: ShiftRows row 3 shifted left by 1 instead of left by 3
# The 4th byte in each group of 4 in the concatenation is wrong
# Buggy:  s7, s11, s15, s3  (left shift 1)
# Correct: s15, s3, s7, s11 (left shift 3)
code = code.replace(
    "s0,  s5,  s10, s7,\n"
    "                s4,  s9,  s14, s11,\n"
    "                s8,  s13, s2,  s15,\n"
    "                s12, s1,  s6,  s3",
    "s0,  s5,  s10, s15,\n"
    "                s4,  s9,  s14, s3,\n"
    "                s8,  s13, s2,  s7,\n"
    "                s12, s1,  s6,  s11"
)

# Bug 3: RotWord rotates right by 1 byte instead of left by 1 byte
# Right rotation: {a3, a0, a1, a2} -- WRONG
# Left rotation:  {a1, a2, a3, a0} -- CORRECT
code = code.replace(
    "{sbox(w3[7:0]),   sbox(w3[31:24]), sbox(w3[23:16]), sbox(w3[15:8])}",
    "{sbox(w3[23:16]), sbox(w3[15:8]),  sbox(w3[7:0]),   sbox(w3[31:24])}"
)

with open("/app/aes128.v", "w") as f:
    f.write(code)

print("Applied 3 fixes to /app/aes128.v:")
print("  1. xtime reduction polynomial: 0x1d -> 0x1b")
print("  2. ShiftRows row 3: left-shift-1 -> left-shift-3")
print("  3. RotWord: right-rotate -> left-rotate")
