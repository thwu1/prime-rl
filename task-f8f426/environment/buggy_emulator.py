#!/usr/bin/env python3
"""NMOS 6502 CPU Emulator — implements all official opcodes."""

import json
import sys


class CPU6502:
    def __init__(self):
        self.a = 0
        self.x = 0
        self.y = 0
        self.sp = 0xFD
        self.pc = 0
        self.c = 0  # Carry
        self.z = 0  # Zero
        self.i = 0  # Interrupt disable
        self.d = 0  # Decimal
        self.v = 0  # Overflow
        self.n = 0  # Negative
        self.mem = bytearray(65536)

    def load_image(self, path):
        with open(path, 'rb') as f:
            data = f.read()
        self.mem[:len(data)] = data

    def reset(self):
        self.pc = self.mem[0xFFFC] | (self.mem[0xFFFD] << 8)
        self.sp = 0xFD
        self.i = 1
        self.d = 0
        self.a = self.x = self.y = 0
        self.c = self.z = self.v = self.n = 0

    def read(self, addr):
        return self.mem[addr & 0xFFFF]

    def write(self, addr, val):
        self.mem[addr & 0xFFFF] = val & 0xFF

    def read16_zp(self, addr):
        lo = self.mem[addr & 0xFF]
        hi = self.mem[(addr + 1) & 0xFF]
        return lo | (hi << 8)

    def read16(self, addr):
        lo = self.mem[addr & 0xFFFF]
        hi = self.mem[(addr + 1) & 0xFFFF]
        return lo | (hi << 8)

    def push(self, val):
        self.mem[0x100 + self.sp] = val & 0xFF
        self.sp = (self.sp - 1) & 0xFF

    def pull(self):
        self.sp = (self.sp + 1) & 0xFF
        return self.mem[0x100 + self.sp]

    def push16(self, val):
        self.push((val >> 8) & 0xFF)
        self.push(val & 0xFF)

    def pull16(self):
        lo = self.pull()
        hi = self.pull()
        return lo | (hi << 8)

    def get_p(self):
        return (self.c
                | (self.z << 1)
                | (self.i << 2)
                | (self.d << 3)
                | (1 << 5)
                | (self.v << 6)
                | (self.n << 7))

    def set_p(self, val):
        self.c = val & 1
        self.z = (val >> 1) & 1
        self.i = (val >> 2) & 1
        self.d = (val >> 3) & 1
        self.v = (val >> 6) & 1
        self.n = (val >> 7) & 1

    def set_nz(self, val):
        self.z = 1 if (val & 0xFF) == 0 else 0
        self.n = 1 if (val & 0x80) else 0

    def fetch(self):
        val = self.mem[self.pc & 0xFFFF]
        self.pc = (self.pc + 1) & 0xFFFF
        return val

    def fetch16(self):
        lo = self.fetch()
        hi = self.fetch()
        return lo | (hi << 8)

    # Addressing modes
    def am_imm(self):
        return self.fetch()

    def am_zp(self):
        return self.fetch()

    def am_zpx(self):
        return (self.fetch() + self.x) & 0xFF

    def am_zpy(self):
        return (self.fetch() + self.y) & 0xFF

    def am_abs(self):
        return self.fetch16()

    def am_absx(self):
        return (self.fetch16() + self.x) & 0xFFFF

    def am_absy(self):
        return (self.fetch16() + self.y) & 0xFFFF

    def am_indx(self):
        zp = (self.fetch() + self.x) & 0xFF
        return self.read16_zp(zp)

    def am_indy(self):
        zp = self.fetch()
        base = self.mem[zp] | (self.mem[(zp + 1) & 0xFFFF] << 8)
        return (base + self.y) & 0xFFFF

    # ALU operations
    def do_adc(self, val):
        if self.d:
            al = (self.a & 0x0F) + (val & 0x0F) + self.c
            if al > 9:
                al += 6
            ah = (self.a >> 4) + (val >> 4) + (1 if al > 0x0F else 0)
            bres = self.a + val + self.c
            self.z = 1 if (bres & 0xFF) == 0 else 0
            tmp = ((ah << 4) | (al & 0x0F)) & 0xFF
            self.n = 1 if (tmp & 0x80) else 0
            self.v = 1 if ((~(self.a ^ val) & (self.a ^ tmp)) & 0x80) else 0
            self.c = 1 if ah > 0x0F else 0
            self.a = ((ah << 4) | (al & 0x0F)) & 0xFF
        else:
            res = self.a + val + self.c
            self.v = 1 if ((~(self.a ^ val) & (self.a ^ res)) & 0x80) else 0
            self.c = 1 if res > 0xFF else 0
            self.a = res & 0xFF
            self.set_nz(self.a)

    def do_sbc(self, val):
        if self.d:
            al = (self.a & 0x0F) - (val & 0x0F) - (1 - self.c)
            borrow_lo = 0
            if al < 0:
                al = ((al - 6) & 0x0F)
                borrow_lo = 1
            ah = (self.a >> 4) - (val >> 4) - borrow_lo
            bres = self.a - val - (1 - self.c)
            self.c = 1 if bres >= 0 else 0
            self.z = 1 if (bres & 0xFF) == 0 else 0
            self.n = 1 if (bres & 0x80) else 0
            self.v = 1 if (((self.a ^ val) & (self.a ^ bres)) & 0x80) else 0
            if ah < 0:
                ah -= 6
            self.a = ((ah << 4) | (al & 0x0F)) & 0xFF
        else:
            res = self.a - val - (1 - self.c)
            self.v = 1 if (((self.a ^ val) & (self.a ^ res)) & 0x80) else 0
            self.c = 1 if res >= 0 else 0
            self.a = res & 0xFF
            self.set_nz(self.a)

    def do_cmp(self, reg, val):
        res = reg - val
        self.c = 1 if res >= 0 else 0
        self.set_nz(res & 0xFF)

    def do_branch(self, cond):
        off = self.fetch()
        if off & 0x80:
            off -= 256
        if cond:
            self.pc = (self.pc + off) & 0xFFFF

    def do_asl(self, val):
        self.c = 1 if (val & 0x80) else 0
        val = (val << 1) & 0xFF
        self.set_nz(val)
        return val

    def do_lsr(self, val):
        self.c = val & 1
        val = (val >> 1) & 0xFF
        self.set_nz(val)
        return val

    def do_rol(self, val):
        oc = self.c
        self.c = 1 if (val & 0x80) else 0
        val = ((val << 1) | oc) & 0xFF
        self.set_nz(val)
        return val

    def do_ror(self, val):
        oc = self.c
        self.c = val & 1
        val = ((val >> 1) | (oc << 7)) & 0xFF
        self.set_nz(val)
        return val

    def step(self):
        op = self.fetch()

        if op == 0x00:  # BRK
            self.pc = (self.pc + 1) & 0xFFFF
            self.push16(self.pc)
            self.push(self.get_p() | 0x20)
            self.i = 1
            self.pc = self.mem[0xFFFE] | (self.mem[0xFFFF] << 8)
        elif op == 0x01:  # ORA (zp,X)
            a = self.am_indx(); self.a |= self.read(a); self.set_nz(self.a)
        elif op == 0x05:  # ORA zp
            a = self.am_zp(); self.a |= self.read(a); self.set_nz(self.a)
        elif op == 0x06:  # ASL zp
            a = self.am_zp(); self.write(a, self.do_asl(self.read(a)))
        elif op == 0x08:  # PHP
            self.push(self.get_p() | 0x20)
        elif op == 0x09:  # ORA #
            self.a |= self.am_imm(); self.set_nz(self.a)
        elif op == 0x0A:  # ASL A
            self.a = self.do_asl(self.a)
        elif op == 0x0D:  # ORA abs
            a = self.am_abs(); self.a |= self.read(a); self.set_nz(self.a)
        elif op == 0x0E:  # ASL abs
            a = self.am_abs(); self.write(a, self.do_asl(self.read(a)))
        elif op == 0x10:  # BPL
            self.do_branch(not self.n)
        elif op == 0x11:  # ORA (zp),Y
            a = self.am_indy(); self.a |= self.read(a); self.set_nz(self.a)
        elif op == 0x15:  # ORA zp,X
            a = self.am_zpx(); self.a |= self.read(a); self.set_nz(self.a)
        elif op == 0x16:  # ASL zp,X
            a = self.am_zpx(); self.write(a, self.do_asl(self.read(a)))
        elif op == 0x18:  # CLC
            self.c = 0
        elif op == 0x19:  # ORA abs,Y
            a = self.am_absy(); self.a |= self.read(a); self.set_nz(self.a)
        elif op == 0x1D:  # ORA abs,X
            a = self.am_absx(); self.a |= self.read(a); self.set_nz(self.a)
        elif op == 0x1E:  # ASL abs,X
            a = self.am_absx(); self.write(a, self.do_asl(self.read(a)))
        elif op == 0x20:  # JSR abs
            a = self.fetch16(); self.push16((self.pc - 1) & 0xFFFF); self.pc = a
        elif op == 0x21:  # AND (zp,X)
            a = self.am_indx(); self.a &= self.read(a); self.set_nz(self.a)
        elif op == 0x24:  # BIT zp
            a = self.am_zp(); v = self.read(a)
            self.z = 1 if (self.a & v) == 0 else 0
            self.n = 1 if (v & 0x80) else 0
            self.v = 1 if (v & 0x40) else 0
        elif op == 0x25:  # AND zp
            a = self.am_zp(); self.a &= self.read(a); self.set_nz(self.a)
        elif op == 0x26:  # ROL zp
            a = self.am_zp(); self.write(a, self.do_rol(self.read(a)))
        elif op == 0x28:  # PLP
            self.set_p(self.pull())
        elif op == 0x29:  # AND #
            self.a &= self.am_imm(); self.set_nz(self.a)
        elif op == 0x2A:  # ROL A
            self.a = self.do_rol(self.a)
        elif op == 0x2C:  # BIT abs
            a = self.am_abs(); v = self.read(a)
            self.z = 1 if (self.a & v) == 0 else 0
            self.n = 1 if (v & 0x80) else 0
            self.v = 1 if (v & 0x40) else 0
        elif op == 0x2D:  # AND abs
            a = self.am_abs(); self.a &= self.read(a); self.set_nz(self.a)
        elif op == 0x2E:  # ROL abs
            a = self.am_abs(); self.write(a, self.do_rol(self.read(a)))
        elif op == 0x30:  # BMI
            self.do_branch(self.n == 1)
        elif op == 0x31:  # AND (zp),Y
            a = self.am_indy(); self.a &= self.read(a); self.set_nz(self.a)
        elif op == 0x35:  # AND zp,X
            a = self.am_zpx(); self.a &= self.read(a); self.set_nz(self.a)
        elif op == 0x36:  # ROL zp,X
            a = self.am_zpx(); self.write(a, self.do_rol(self.read(a)))
        elif op == 0x38:  # SEC
            self.c = 1
        elif op == 0x39:  # AND abs,Y
            a = self.am_absy(); self.a &= self.read(a); self.set_nz(self.a)
        elif op == 0x3D:  # AND abs,X
            a = self.am_absx(); self.a &= self.read(a); self.set_nz(self.a)
        elif op == 0x3E:  # ROL abs,X
            a = self.am_absx(); self.write(a, self.do_rol(self.read(a)))
        elif op == 0x40:  # RTI
            self.set_p(self.pull()); self.pc = self.pull16()
        elif op == 0x41:  # EOR (zp,X)
            a = self.am_indx(); self.a ^= self.read(a); self.set_nz(self.a)
        elif op == 0x45:  # EOR zp
            a = self.am_zp(); self.a ^= self.read(a); self.set_nz(self.a)
        elif op == 0x46:  # LSR zp
            a = self.am_zp(); self.write(a, self.do_lsr(self.read(a)))
        elif op == 0x48:  # PHA
            self.push(self.a)
        elif op == 0x49:  # EOR #
            self.a ^= self.am_imm(); self.set_nz(self.a)
        elif op == 0x4A:  # LSR A
            self.a = self.do_lsr(self.a)
        elif op == 0x4C:  # JMP abs
            self.pc = self.fetch16()
        elif op == 0x4D:  # EOR abs
            a = self.am_abs(); self.a ^= self.read(a); self.set_nz(self.a)
        elif op == 0x4E:  # LSR abs
            a = self.am_abs(); self.write(a, self.do_lsr(self.read(a)))
        elif op == 0x50:  # BVC
            self.do_branch(not self.v)
        elif op == 0x51:  # EOR (zp),Y
            a = self.am_indy(); self.a ^= self.read(a); self.set_nz(self.a)
        elif op == 0x55:  # EOR zp,X
            a = self.am_zpx(); self.a ^= self.read(a); self.set_nz(self.a)
        elif op == 0x56:  # LSR zp,X
            a = self.am_zpx(); self.write(a, self.do_lsr(self.read(a)))
        elif op == 0x58:  # CLI
            self.i = 0
        elif op == 0x59:  # EOR abs,Y
            a = self.am_absy(); self.a ^= self.read(a); self.set_nz(self.a)
        elif op == 0x5D:  # EOR abs,X
            a = self.am_absx(); self.a ^= self.read(a); self.set_nz(self.a)
        elif op == 0x5E:  # LSR abs,X
            a = self.am_absx(); self.write(a, self.do_lsr(self.read(a)))
        elif op == 0x60:  # RTS
            self.pc = (self.pull16() + 1) & 0xFFFF
        elif op == 0x61:  # ADC (zp,X)
            self.do_adc(self.read(self.am_indx()))
        elif op == 0x65:  # ADC zp
            self.do_adc(self.read(self.am_zp()))
        elif op == 0x66:  # ROR zp
            a = self.am_zp(); self.write(a, self.do_ror(self.read(a)))
        elif op == 0x68:  # PLA
            self.a = self.pull(); self.set_nz(self.a)
        elif op == 0x69:  # ADC #
            self.do_adc(self.am_imm())
        elif op == 0x6A:  # ROR A
            self.a = self.do_ror(self.a)
        elif op == 0x6C:  # JMP (abs)
            a = self.fetch16(); self.pc = self.read16(a)
        elif op == 0x6D:  # ADC abs
            self.do_adc(self.read(self.am_abs()))
        elif op == 0x6E:  # ROR abs
            a = self.am_abs(); self.write(a, self.do_ror(self.read(a)))
        elif op == 0x70:  # BVS
            self.do_branch(self.v == 1)
        elif op == 0x71:  # ADC (zp),Y
            self.do_adc(self.read(self.am_indy()))
        elif op == 0x75:  # ADC zp,X
            self.do_adc(self.read(self.am_zpx()))
        elif op == 0x76:  # ROR zp,X
            a = self.am_zpx(); self.write(a, self.do_ror(self.read(a)))
        elif op == 0x78:  # SEI
            self.i = 1
        elif op == 0x79:  # ADC abs,Y
            self.do_adc(self.read(self.am_absy()))
        elif op == 0x7D:  # ADC abs,X
            self.do_adc(self.read(self.am_absx()))
        elif op == 0x7E:  # ROR abs,X
            a = self.am_absx(); self.write(a, self.do_ror(self.read(a)))
        elif op == 0x81:  # STA (zp,X)
            self.write(self.am_indx(), self.a)
        elif op == 0x84:  # STY zp
            self.write(self.am_zp(), self.y)
        elif op == 0x85:  # STA zp
            self.write(self.am_zp(), self.a)
        elif op == 0x86:  # STX zp
            self.write(self.am_zp(), self.x)
        elif op == 0x88:  # DEY
            self.y = (self.y - 1) & 0xFF; self.set_nz(self.y)
        elif op == 0x8A:  # TXA
            self.a = self.x; self.set_nz(self.a)
        elif op == 0x8C:  # STY abs
            self.write(self.am_abs(), self.y)
        elif op == 0x8D:  # STA abs
            self.write(self.am_abs(), self.a)
        elif op == 0x8E:  # STX abs
            self.write(self.am_abs(), self.x)
        elif op == 0x90:  # BCC
            self.do_branch(not self.c)
        elif op == 0x91:  # STA (zp),Y
            self.write(self.am_indy(), self.a)
        elif op == 0x94:  # STY zp,X
            self.write(self.am_zpx(), self.y)
        elif op == 0x95:  # STA zp,X
            self.write(self.am_zpx(), self.a)
        elif op == 0x96:  # STX zp,Y
            self.write(self.am_zpy(), self.x)
        elif op == 0x98:  # TYA
            self.a = self.y; self.set_nz(self.a)
        elif op == 0x99:  # STA abs,Y
            self.write(self.am_absy(), self.a)
        elif op == 0x9A:  # TXS
            self.sp = self.x
        elif op == 0x9D:  # STA abs,X
            self.write(self.am_absx(), self.a)
        elif op == 0xA0:  # LDY #
            self.y = self.am_imm(); self.set_nz(self.y)
        elif op == 0xA1:  # LDA (zp,X)
            self.a = self.read(self.am_indx()); self.set_nz(self.a)
        elif op == 0xA2:  # LDX #
            self.x = self.am_imm(); self.set_nz(self.x)
        elif op == 0xA4:  # LDY zp
            self.y = self.read(self.am_zp()); self.set_nz(self.y)
        elif op == 0xA5:  # LDA zp
            self.a = self.read(self.am_zp()); self.set_nz(self.a)
        elif op == 0xA6:  # LDX zp
            self.x = self.read(self.am_zp()); self.set_nz(self.x)
        elif op == 0xA8:  # TAY
            self.y = self.a; self.set_nz(self.y)
        elif op == 0xA9:  # LDA #
            self.a = self.am_imm(); self.set_nz(self.a)
        elif op == 0xAA:  # TAX
            self.x = self.a; self.set_nz(self.x)
        elif op == 0xAC:  # LDY abs
            self.y = self.read(self.am_abs()); self.set_nz(self.y)
        elif op == 0xAD:  # LDA abs
            self.a = self.read(self.am_abs()); self.set_nz(self.a)
        elif op == 0xAE:  # LDX abs
            self.x = self.read(self.am_abs()); self.set_nz(self.x)
        elif op == 0xB0:  # BCS
            self.do_branch(self.c == 1)
        elif op == 0xB1:  # LDA (zp),Y
            self.a = self.read(self.am_indy()); self.set_nz(self.a)
        elif op == 0xB4:  # LDY zp,X
            self.y = self.read(self.am_zpx()); self.set_nz(self.y)
        elif op == 0xB5:  # LDA zp,X
            self.a = self.read(self.am_zpx()); self.set_nz(self.a)
        elif op == 0xB6:  # LDX zp,Y
            self.x = self.read(self.am_zpy()); self.set_nz(self.x)
        elif op == 0xB8:  # CLV
            self.v = 0
        elif op == 0xB9:  # LDA abs,Y
            self.a = self.read(self.am_absy()); self.set_nz(self.a)
        elif op == 0xBA:  # TSX
            self.x = self.sp; self.set_nz(self.x)
        elif op == 0xBC:  # LDY abs,X
            self.y = self.read(self.am_absx()); self.set_nz(self.y)
        elif op == 0xBD:  # LDA abs,X
            self.a = self.read(self.am_absx()); self.set_nz(self.a)
        elif op == 0xBE:  # LDX abs,Y
            self.x = self.read(self.am_absy()); self.set_nz(self.x)
        elif op == 0xC0:  # CPY #
            self.do_cmp(self.y, self.am_imm())
        elif op == 0xC1:  # CMP (zp,X)
            self.do_cmp(self.a, self.read(self.am_indx()))
        elif op == 0xC4:  # CPY zp
            self.do_cmp(self.y, self.read(self.am_zp()))
        elif op == 0xC5:  # CMP zp
            self.do_cmp(self.a, self.read(self.am_zp()))
        elif op == 0xC6:  # DEC zp
            a = self.am_zp(); v = (self.read(a) - 1) & 0xFF; self.write(a, v); self.set_nz(v)
        elif op == 0xC8:  # INY
            self.y = (self.y + 1) & 0xFF; self.set_nz(self.y)
        elif op == 0xC9:  # CMP #
            self.do_cmp(self.a, self.am_imm())
        elif op == 0xCA:  # DEX
            self.x = (self.x - 1) & 0xFF; self.set_nz(self.x)
        elif op == 0xCC:  # CPY abs
            self.do_cmp(self.y, self.read(self.am_abs()))
        elif op == 0xCD:  # CMP abs
            self.do_cmp(self.a, self.read(self.am_abs()))
        elif op == 0xCE:  # DEC abs
            a = self.am_abs(); v = (self.read(a) - 1) & 0xFF; self.write(a, v); self.set_nz(v)
        elif op == 0xD0:  # BNE
            self.do_branch(not self.z)
        elif op == 0xD1:  # CMP (zp),Y
            self.do_cmp(self.a, self.read(self.am_indy()))
        elif op == 0xD5:  # CMP zp,X
            self.do_cmp(self.a, self.read(self.am_zpx()))
        elif op == 0xD6:  # DEC zp,X
            a = self.am_zpx(); v = (self.read(a) - 1) & 0xFF; self.write(a, v); self.set_nz(v)
        elif op == 0xD8:  # CLD
            self.d = 0
        elif op == 0xD9:  # CMP abs,Y
            self.do_cmp(self.a, self.read(self.am_absy()))
        elif op == 0xDD:  # CMP abs,X
            self.do_cmp(self.a, self.read(self.am_absx()))
        elif op == 0xDE:  # DEC abs,X
            a = self.am_absx(); v = (self.read(a) - 1) & 0xFF; self.write(a, v); self.set_nz(v)
        elif op == 0xE0:  # CPX #
            self.do_cmp(self.x, self.am_imm())
        elif op == 0xE1:  # SBC (zp,X)
            self.do_sbc(self.read(self.am_indx()))
        elif op == 0xE4:  # CPX zp
            self.do_cmp(self.x, self.read(self.am_zp()))
        elif op == 0xE5:  # SBC zp
            self.do_sbc(self.read(self.am_zp()))
        elif op == 0xE6:  # INC zp
            a = self.am_zp(); v = (self.read(a) + 1) & 0xFF; self.write(a, v); self.set_nz(v)
        elif op == 0xE8:  # INX
            self.x = (self.x + 1) & 0xFF; self.set_nz(self.x)
        elif op == 0xE9:  # SBC #
            self.do_sbc(self.am_imm())
        elif op == 0xEA:  # NOP
            pass
        elif op == 0xEC:  # CPX abs
            self.do_cmp(self.x, self.read(self.am_abs()))
        elif op == 0xED:  # SBC abs
            self.do_sbc(self.read(self.am_abs()))
        elif op == 0xEE:  # INC abs
            a = self.am_abs(); v = (self.read(a) + 1) & 0xFF; self.write(a, v); self.set_nz(v)
        elif op == 0xF0:  # BEQ
            self.do_branch(self.z == 1)
        elif op == 0xF1:  # SBC (zp),Y
            self.do_sbc(self.read(self.am_indy()))
        elif op == 0xF5:  # SBC zp,X
            self.do_sbc(self.read(self.am_zpx()))
        elif op == 0xF6:  # INC zp,X
            a = self.am_zpx(); v = (self.read(a) + 1) & 0xFF; self.write(a, v); self.set_nz(v)
        elif op == 0xF8:  # SED
            self.d = 1
        elif op == 0xF9:  # SBC abs,Y
            self.do_sbc(self.read(self.am_absy()))
        elif op == 0xFD:  # SBC abs,X
            self.do_sbc(self.read(self.am_absx()))
        elif op == 0xFE:  # INC abs,X
            a = self.am_absx(); v = (self.read(a) + 1) & 0xFF; self.write(a, v); self.set_nz(v)

    def run(self, max_instr=1000000):
        self.reset()
        for i in range(max_instr):
            prev = self.pc
            self.step()
            if self.pc == prev:
                return i + 1
        return max_instr


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else '/app/test_suite.bin'
    cpu = CPU6502()
    cpu.load_image(path)
    n = cpu.run()

    results = {}
    for addr in range(0x0200, 0x0212):
        results[f"0x{addr:04X}"] = cpu.mem[addr]

    with open('/app/output.json', 'w') as f:
        json.dump({"results": results}, f, indent=2)

    print(f"Executed {n} instructions")
    for k, v in sorted(results.items()):
        print(f"  {k}: {v} (0x{v:02X})")


if __name__ == '__main__':
    main()
