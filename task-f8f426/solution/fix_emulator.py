#!/usr/bin/env python3
"""
Fix all conformance failures identified in the NMOS 6502 emulator.

Based on the conformance evaluation, 4 bugs were identified:

1. JMP indirect ($6C) — read16() does not implement the NMOS page-boundary
   anomaly. On the original 6502, JMP ($xxFF) fetches the high byte from $xx00
   (wrapping within the page), not from $(xx+1)00.

2. Indirect-Y addressing (am_indy) — the zero-page pointer fetch does not
   wrap within the zero page. When the pointer is at $FF, the high byte
   should come from $00 (ZP wrap), not from $0100.

3. PHP/BRK status push — only bit 5 is ORed in (0x20). The B flag (bit 4)
   must also be set, so the mask should be 0x30.

4. BCD ADC — missing high-nibble decimal correction. After computing the
   high nibble sum, values > 9 must be corrected by adding 6 before
   checking the carry flag.
"""

import sys

with open('/app/emulator.py', 'r') as f:
    code = f.read()

fixes_applied = 0

# Fix 1: JMP indirect page-boundary wrap (NMOS-specific anomaly)
old_read16 = """    def read16(self, addr):
        lo = self.mem[addr & 0xFFFF]
        hi = self.mem[(addr + 1) & 0xFFFF]
        return lo | (hi << 8)"""

new_read16 = """    def read16(self, addr):
        lo = self.mem[addr & 0xFFFF]
        hi_addr = (addr & 0xFF00) | ((addr + 1) & 0xFF)
        hi = self.mem[hi_addr & 0xFFFF]
        return lo | (hi << 8)"""

if old_read16 in code:
    code = code.replace(old_read16, new_read16)
    fixes_applied += 1
    print("Fix 1: JMP indirect page-boundary wrap applied")

# Fix 2: Indirect-Y zero-page pointer wrapping
old_indy = """    def am_indy(self):
        zp = self.fetch()
        base = self.mem[zp] | (self.mem[(zp + 1) & 0xFFFF] << 8)
        return (base + self.y) & 0xFFFF"""

new_indy = """    def am_indy(self):
        zp = self.fetch()
        base = self.mem[zp & 0xFF] | (self.mem[(zp + 1) & 0xFF] << 8)
        return (base + self.y) & 0xFFFF"""

if old_indy in code:
    code = code.replace(old_indy, new_indy)
    fixes_applied += 1
    print("Fix 2: Indirect-Y ZP pointer wrap applied")

# Fix 3: PHP and BRK must set B flag (bit 4) — change 0x20 to 0x30
count_before = code.count('self.push(self.get_p() | 0x20)')
if count_before > 0:
    code = code.replace('self.push(self.get_p() | 0x20)', 'self.push(self.get_p() | 0x30)')
    fixes_applied += 1
    print(f"Fix 3: PHP/BRK B-flag applied ({count_before} occurrences)")

# Fix 4: BCD ADC high-nibble correction
old_bcd = """            self.v = 1 if ((~(self.a ^ val) & (self.a ^ tmp)) & 0x80) else 0
            self.c = 1 if ah > 0x0F else 0"""

new_bcd = """            self.v = 1 if ((~(self.a ^ val) & (self.a ^ tmp)) & 0x80) else 0
            if ah > 9:
                ah += 6
            self.c = 1 if ah > 0x0F else 0"""

if old_bcd in code:
    code = code.replace(old_bcd, new_bcd)
    fixes_applied += 1
    print("Fix 4: BCD ADC high-nibble correction applied")

with open('/app/emulator.py', 'w') as f:
    f.write(code)

print(f"\nTotal fixes applied: {fixes_applied}")
if fixes_applied < 4:
    print("WARNING: Not all fixes matched — emulator source may have changed", file=sys.stderr)
    sys.exit(1)
