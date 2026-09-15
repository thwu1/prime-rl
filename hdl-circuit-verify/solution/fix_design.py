#!/usr/bin/env python3
"""Fix the four bugs in the ALU design."""


with open('/app/design.py') as f:
    code = f.read()

# Bug 1 (carry_logic): full_adder carry term uses raw input 'a' instead of
# the intermediate XOR 's1 = a ^ b'.  Correct carry-out formula is
# (a & b) | ((a ^ b) & cin).  Using 'a & cin' drops carry when a=0,b=1,cin=1.
code = code.replace('c2 = a & cin', 'c2 = s1 & cin')

# Bug 2 (complement): subtractor omits the +1 for two's complement.
# a - b = a + ~b + 1, but carry-in is const(0), computing a + ~b = a - b - 1.
code = code.replace(
    'result, _ = ripple_adder(a, not_b, const(0))',
    'result, _ = ripple_adder(a, not_b, const(1))'
)

# Bug 3 (indexing): shift_right uses modular wrap, producing rotation
# instead of logical right shift.  Must zero-fill the vacated MSB.
code = code.replace(
    'Bus([a[(i + 1) % n] for i in range(n)])',
    'Bus([a[i + 1] if i + 1 < n else const(0) for i in range(n)])'
)

# Bug 4 (mux_wiring): XOR/NOT mux arguments are swapped.
# mux(sel, if_one, if_zero): opcode 100 (XOR) has bit0=0 → selects if_zero,
# which should be res_xor but was res_not, and vice versa.
code = code.replace(
    'mux(opcode[0], res_xor, res_not)',
    'mux(opcode[0], res_not, res_xor)'
)

with open('/app/design.py', 'w') as f:
    f.write(code)

print("Fixed 4 bugs in design.py")
