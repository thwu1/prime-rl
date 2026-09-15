#!/usr/bin/env python3
"""
Patches cpu8088.py to fix five hardware-validation bugs.

"""

import re

with open('/app/cpu8088.py', 'r') as f:
    code = f.read()

# ---- Bug 1 & 2: DAA and DAS second-condition uses adjusted AL instead of
# saved old_al.  Both _daa() and _das() contain:
#     if al > 0x99 or old_cf:
# which should be:
#     if old_al > 0x99 or old_cf:
code = code.replace(
    'if al > 0x99 or old_cf:',
    'if old_al > 0x99 or old_cf:'
)

# ---- Bug 3: AAM hardcodes divisor to 10 instead of using the immediate byte.
# _aam() reads _base = self.fetch_byte() but then divides by 10.
code = code.replace(
    'self.set_reg8(4, al // 10)',
    'self.set_reg8(4, al // _base)'
)
code = code.replace(
    'self.set_reg8(0, al % 10)',
    'self.set_reg8(0, al % _base)'
)

# ---- Bug 4: AAD hardcodes multiplier to 10 instead of using the immediate.
# _aad() reads _base but multiplies ah * 10.
code = code.replace(
    '(ah * 10 + al)',
    '(ah * _base + al)'
)

# ---- Bug 5: Shift/rotate masks count with & 0x1F (80286+ behavior).
# The real 8088 does NOT mask the shift count.
code = code.replace(
    '        count = count & 0x1F\n',
    ''
)

# ---- Bug 6: SALC (opcode 0xD6) is missing from execute_one().
# Insert it just before the final else/raise.
salc_block = (
    '        # SALC - Set AL from Carry (undocumented 8088 opcode)\n'
    '        elif opcode == 0xD6:\n'
    '            if self.get_flag(self.CF):\n'
    '                self.set_reg8(0, 0xFF)\n'
    '            else:\n'
    '                self.set_reg8(0, 0x00)\n\n'
)
code = code.replace(
    '        else:\n            raise ValueError(f"Unhandled opcode: 0x{opcode:02X}")',
    salc_block +
    '        else:\n            raise ValueError(f"Unhandled opcode: 0x{opcode:02X}")'
)

with open('/app/cpu8088.py', 'w') as f:
    f.write(code)

print("All patches applied.")
