#!/usr/bin/env python3
"""Fix the three bugs in the ALU design."""


import json

with open('/app/design.py') as f:
    code = f.read()

# Bug 1: full_adder carry computation uses wrong signal.
# The carry term c2 must use the intermediate XOR result (s1 = a ^ b),
# not the raw input a.  c2 = s1 & cin  is the correct form because
# carry-out = (a & b) | ((a ^ b) & cin).  Using 'a & cin' drops the
# carry whenever a=0, b=1, cin=1.
code = code.replace('c2 = a & cin', 'c2 = s1 & cin')

# Bug 2: shift_right performs a rotation instead of a logical right shift.
# a[(i+1) % n] wraps the LSB around to the MSB position.  A logical
# right shift must zero-fill the vacated MSB.
code = code.replace(
    'Bus([a[(i + 1) % n] for i in range(n)])',
    'Bus([a[i + 1] if i + 1 < n else const(0) for i in range(n)])'
)

# Bug 3: XOR and NOT are swapped in the mux tree.
# mux(sel, if_one, if_zero) returns if_one when sel=1.
# For opcode 100 (XOR) sel=opcode[0]=0, so if_zero must be res_xor.
# For opcode 101 (NOT) sel=opcode[0]=1, so if_one  must be res_not.
# The buggy line has them reversed.
code = code.replace(
    'mux(opcode[0], res_xor, res_not)',
    'mux(opcode[0], res_not, res_xor)'
)

with open('/app/design.py', 'w') as f:
    f.write(code)

fixes = [
    {
        "bug_number": 1,
        "file": "design.py",
        "function": "full_adder",
        "line_content": "c2 = a & cin",
        "description": (
            "Carry computation uses the raw input 'a' instead of the "
            "intermediate XOR result 's1 = a ^ b'.  The correct carry-out "
            "formula is (a & b) | ((a ^ b) & cin).  Using 'a & cin' loses "
            "the carry whenever a=0, b=1, cin=1, corrupting addition and "
            "subtraction for many operand combinations."
        ),
        "fix": "Changed 'c2 = a & cin' to 'c2 = s1 & cin'"
    },
    {
        "bug_number": 2,
        "file": "design.py",
        "function": "shift_right",
        "line_content": "Bus([a[(i + 1) % n] for i in range(n)])",
        "description": (
            "Modular indexing '(i + 1) % n' wraps the least-significant "
            "bit into the most-significant position, turning a logical "
            "right shift into a right rotation.  Odd inputs gain a "
            "spurious high bit."
        ),
        "fix": (
            "Changed to 'a[i + 1] if i + 1 < n else const(0)' to "
            "zero-fill the vacated MSB position"
        )
    },
    {
        "bug_number": 3,
        "file": "design.py",
        "function": "build_alu",
        "line_content": "m2 = mux(opcode[0], res_xor, res_not)",
        "description": (
            "The if_one and if_zero arguments to the mux selecting between "
            "XOR (opcode 100) and NOT (opcode 101) are reversed.  Because "
            "mux returns if_one when sel=1, opcode 100 (sel=0) selects "
            "if_zero, which should be res_xor but was res_not, and vice "
            "versa."
        ),
        "fix": "Swapped to 'mux(opcode[0], res_not, res_xor)'"
    }
]

with open('/app/fixes.json', 'w') as f:
    json.dump(fixes, f, indent=2)

print("All 3 bugs fixed. Wrote /app/fixes.json")
