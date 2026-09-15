#!/usr/bin/env python3
"""Fix all seven bugs in the MOS 6502 CPU emulator.

Bug 1: Zero-page indexed X addressing uses 16-bit mask instead of 8-bit
Bug 2: Indirect JMP doesn't wrap high-byte read within page at boundary
Bug 3: BCD ADC low nibble adjustment threshold is >0x0F instead of >9
Bug 4: ROL uses newly computed carry for bit 0 instead of old carry
Bug 5: BRK doesn't skip the signature byte before pushing PC
Bug 6: Indexed indirect X doesn't wrap high-byte read within zero page
Bug 7: SBC binary mode uses wrong overflow flag formula (ADC's formula)

"""

with open('/app/cpu6502.py', 'r') as f:
    code = f.read()

# Fix 1: Zero-page X wrapping — must mask to 8 bits
code = code.replace(
    "return (base + self.X) & 0xFFFF",
    "return (base + self.X) & 0xFF"
)

# Fix 2: Indirect JMP page boundary — high byte wraps within same page
# Use full method context to avoid matching _izx
code = code.replace(
    """    def _ind(self):
        ptr = self.read16(self.PC)
        self.PC = (self.PC + 2) & 0xFFFF
        lo = self.read(ptr)
        hi = self.read((ptr + 1) & 0xFFFF)
        return (hi << 8) | lo""",
    """    def _ind(self):
        ptr = self.read16(self.PC)
        self.PC = (self.PC + 2) & 0xFFFF
        lo = self.read(ptr)
        hi = self.read((ptr & 0xFF00) | ((ptr + 1) & 0x00FF))
        return (hi << 8) | lo"""
)

# Fix 3: BCD ADC low nibble threshold — adjust when >9 not >0x0F
code = code.replace(
    "if lo > 0x0F:",
    "if lo > 9:"
)

# Fix 4a: ROL accumulator — save old carry before computing new carry
code = code.replace(
    """    def _rol_a(self):
        new_carry = bool(self.A & 0x80)
        self.A = (self.A << 1) & 0xFF
        self.C = new_carry
        if self.C:
            self.A |= 0x01
        self.update_nz(self.A)""",
    """    def _rol_a(self):
        old_carry = self.C
        self.C = bool(self.A & 0x80)
        self.A = (self.A << 1) & 0xFF
        if old_carry:
            self.A |= 0x01
        self.update_nz(self.A)"""
)

# Fix 4b: ROL memory — save old carry before computing new carry
code = code.replace(
    """    def _rol(self, addr):
        val = self.read(addr)
        new_carry = bool(val & 0x80)
        val = (val << 1) & 0xFF
        self.C = new_carry
        if self.C:
            val |= 0x01
        self.write(addr, val)
        self.update_nz(val)""",
    """    def _rol(self, addr):
        val = self.read(addr)
        old_carry = self.C
        self.C = bool(val & 0x80)
        val = (val << 1) & 0xFF
        if old_carry:
            val |= 0x01
        self.write(addr, val)
        self.update_nz(val)"""
)

# Fix 5: BRK must increment PC past signature byte before pushing
code = code.replace(
    """    def _brk(self):
        self.push16(self.PC)""",
    """    def _brk(self):
        self.PC = (self.PC + 1) & 0xFFFF
        self.push16(self.PC)"""
)

# Fix 6: Indexed indirect X — high byte must wrap within zero page
code = code.replace(
    """        ptr = (base + self.X) & 0xFF
        lo = self.read(ptr)
        hi = self.read((ptr + 1) & 0xFFFF)
        return (hi << 8) | lo""",
    """        ptr = (base + self.X) & 0xFF
        lo = self.read(ptr)
        hi = self.read((ptr + 1) & 0xFF)
        return (hi << 8) | lo"""
)

# Fix 7: SBC binary overflow flag — remove erroneous 'not'
# SBC needs ((A ^ val) & 0x80) [different signs], not the ADC formula
code = code.replace(
    """        result = self.A - val - (0 if self.C else 1)
            self.V = bool(
                not ((self.A ^ val) & 0x80) and ((self.A ^ result) & 0x80)
            )""",
    """        result = self.A - val - (0 if self.C else 1)
            self.V = bool(
                ((self.A ^ val) & 0x80) and ((self.A ^ result) & 0x80)
            )"""
)

with open('/app/cpu6502.py', 'w') as f:
    f.write(code)

print("All 7 bugs fixed in cpu6502.py")
