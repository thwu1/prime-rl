#!/usr/bin/env python3
"""MOS 6502 CPU Emulator - Subset Implementation

Implements a subset of the MOS 6502 instruction set, sufficient for
running SingleStepTests-format JSON test vectors. Supports all common
addressing modes and the most frequently used instructions.

Usage:
    from cpu6502 import CPU6502
    cpu = CPU6502()
    cpu.load_state(initial_state_dict)
    cpu.step()
    result = cpu.get_state()
"""


class CPU6502:
    def __init__(self):
        self.A = 0
        self.X = 0
        self.Y = 0
        self.SP = 0xFD
        self.PC = 0
        self.C = False
        self.Z = False
        self.I = False
        self.D = False
        self.V = False
        self.N = False
        self.memory = bytearray(65536)

    def reset(self):
        self.A = 0
        self.X = 0
        self.Y = 0
        self.SP = 0xFD
        self.PC = 0
        self.C = False
        self.Z = False
        self.I = False
        self.D = False
        self.V = False
        self.N = False
        self.memory = bytearray(65536)

    def load_state(self, state):
        """Load CPU state from a SingleStepTests-format dict."""
        self.PC = state['pc']
        self.SP = state['s']
        self.A = state['a']
        self.X = state['x']
        self.Y = state['y']
        self.set_status_byte(state['p'])
        self.memory = bytearray(65536)
        for addr, val in state['ram']:
            self.memory[addr] = val

    def get_state(self):
        """Return CPU state as a dict."""
        return {
            'pc': self.PC,
            's': self.SP,
            'a': self.A,
            'x': self.X,
            'y': self.Y,
            'p': self.get_status_byte(),
        }

    def get_status_byte(self, brk=False):
        p = 0x20
        if self.N: p |= 0x80
        if self.V: p |= 0x40
        if brk:    p |= 0x10
        if self.D: p |= 0x08
        if self.I: p |= 0x04
        if self.Z: p |= 0x02
        if self.C: p |= 0x01
        return p

    def set_status_byte(self, p):
        self.N = bool(p & 0x80)
        self.V = bool(p & 0x40)
        self.D = bool(p & 0x08)
        self.I = bool(p & 0x04)
        self.Z = bool(p & 0x02)
        self.C = bool(p & 0x01)

    # ---- Memory access ----

    def read(self, addr):
        return self.memory[addr & 0xFFFF]

    def write(self, addr, val):
        self.memory[addr & 0xFFFF] = val & 0xFF

    def read16(self, addr):
        lo = self.read(addr)
        hi = self.read((addr + 1) & 0xFFFF)
        return (hi << 8) | lo

    def push(self, val):
        self.write(0x0100 | self.SP, val & 0xFF)
        self.SP = (self.SP - 1) & 0xFF

    def pull(self):
        self.SP = (self.SP + 1) & 0xFF
        return self.read(0x0100 | self.SP)

    def push16(self, val):
        self.push((val >> 8) & 0xFF)
        self.push(val & 0xFF)

    def pull16(self):
        lo = self.pull()
        hi = self.pull()
        return (hi << 8) | lo

    def update_nz(self, val):
        self.N = bool(val & 0x80)
        self.Z = (val & 0xFF) == 0

    # ---- Addressing modes ----

    def _imm(self):
        addr = self.PC
        self.PC = (self.PC + 1) & 0xFFFF
        return addr

    def _zp(self):
        addr = self.read(self.PC)
        self.PC = (self.PC + 1) & 0xFFFF
        return addr

    def _zpx(self):
        base = self.read(self.PC)
        self.PC = (self.PC + 1) & 0xFFFF
        return (base + self.X) & 0xFFFF

    def _zpy(self):
        base = self.read(self.PC)
        self.PC = (self.PC + 1) & 0xFFFF
        return (base + self.Y) & 0xFF

    def _abs(self):
        addr = self.read16(self.PC)
        self.PC = (self.PC + 2) & 0xFFFF
        return addr

    def _abx(self):
        base = self.read16(self.PC)
        self.PC = (self.PC + 2) & 0xFFFF
        return (base + self.X) & 0xFFFF

    def _aby(self):
        base = self.read16(self.PC)
        self.PC = (self.PC + 2) & 0xFFFF
        return (base + self.Y) & 0xFFFF

    def _ind(self):
        ptr = self.read16(self.PC)
        self.PC = (self.PC + 2) & 0xFFFF
        lo = self.read(ptr)
        hi = self.read((ptr + 1) & 0xFFFF)
        return (hi << 8) | lo

    def _izx(self):
        base = self.read(self.PC)
        self.PC = (self.PC + 1) & 0xFFFF
        ptr = (base + self.X) & 0xFF
        lo = self.read(ptr)
        hi = self.read((ptr + 1) & 0xFFFF)
        return (hi << 8) | lo

    def _izy(self):
        ptr = self.read(self.PC)
        self.PC = (self.PC + 1) & 0xFFFF
        lo = self.read(ptr)
        hi = self.read((ptr + 1) & 0xFF)
        base = (hi << 8) | lo
        return (base + self.Y) & 0xFFFF

    def _rel(self):
        offset = self.read(self.PC)
        self.PC = (self.PC + 1) & 0xFFFF
        if offset & 0x80:
            offset -= 256
        return (self.PC + offset) & 0xFFFF

    # ---- Instruction handlers ----

    def _adc(self, addr):
        val = self.read(addr)
        if self.D:
            lo = (self.A & 0x0F) + (val & 0x0F) + (1 if self.C else 0)
            carry_lo = 0
            if lo > 0x0F:
                lo += 6
                carry_lo = 1
            hi = (self.A >> 4) + (val >> 4) + carry_lo
            bin_result = self.A + val + (1 if self.C else 0)
            self.V = bool(
                not ((self.A ^ val) & 0x80) and ((self.A ^ bin_result) & 0x80)
            )
            if hi > 9:
                hi += 6
            self.C = hi > 0x0F
            result = ((hi & 0x0F) << 4) | (lo & 0x0F)
            self.N = bool(result & 0x80)
            self.Z = (bin_result & 0xFF) == 0
            self.A = result
        else:
            result = self.A + val + (1 if self.C else 0)
            self.V = bool(
                not ((self.A ^ val) & 0x80) and ((self.A ^ result) & 0x80)
            )
            self.C = result > 0xFF
            self.A = result & 0xFF
            self.update_nz(self.A)

    def _sbc(self, addr):
        val = self.read(addr)
        if self.D:
            lo = (self.A & 0x0F) - (val & 0x0F) - (0 if self.C else 1)
            borrow_lo = 0
            if lo < 0:
                lo += 10
                borrow_lo = 1
            hi = (self.A >> 4) - (val >> 4) - borrow_lo
            bin_result = self.A - val - (0 if self.C else 1)
            self.V = bool(
                ((self.A ^ val) & 0x80) and ((self.A ^ bin_result) & 0x80)
            )
            if hi < 0:
                hi += 10
                self.C = False
            else:
                self.C = True
            self.A = ((hi & 0x0F) << 4) | (lo & 0x0F)
            self.update_nz(bin_result & 0xFF)
        else:
            result = self.A - val - (0 if self.C else 1)
            self.V = bool(
                not ((self.A ^ val) & 0x80) and ((self.A ^ result) & 0x80)
            )
            self.C = result >= 0
            self.A = result & 0xFF
            self.update_nz(self.A)

    def _and(self, addr):
        self.A &= self.read(addr)
        self.update_nz(self.A)

    def _ora(self, addr):
        self.A |= self.read(addr)
        self.update_nz(self.A)

    def _eor(self, addr):
        self.A ^= self.read(addr)
        self.update_nz(self.A)

    def _cmp(self, addr):
        val = self.read(addr)
        result = self.A - val
        self.C = self.A >= val
        self.update_nz(result & 0xFF)

    def _cpx(self, addr):
        val = self.read(addr)
        result = self.X - val
        self.C = self.X >= val
        self.update_nz(result & 0xFF)

    def _cpy(self, addr):
        val = self.read(addr)
        result = self.Y - val
        self.C = self.Y >= val
        self.update_nz(result & 0xFF)

    def _lda(self, addr):
        self.A = self.read(addr)
        self.update_nz(self.A)

    def _ldx(self, addr):
        self.X = self.read(addr)
        self.update_nz(self.X)

    def _ldy(self, addr):
        self.Y = self.read(addr)
        self.update_nz(self.Y)

    def _sta(self, addr):
        self.write(addr, self.A)

    def _stx(self, addr):
        self.write(addr, self.X)

    def _sty(self, addr):
        self.write(addr, self.Y)

    def _inc(self, addr):
        val = (self.read(addr) + 1) & 0xFF
        self.write(addr, val)
        self.update_nz(val)

    def _dec(self, addr):
        val = (self.read(addr) - 1) & 0xFF
        self.write(addr, val)
        self.update_nz(val)

    def _asl(self, addr):
        val = self.read(addr)
        self.C = bool(val & 0x80)
        val = (val << 1) & 0xFF
        self.write(addr, val)
        self.update_nz(val)

    def _asl_a(self):
        self.C = bool(self.A & 0x80)
        self.A = (self.A << 1) & 0xFF
        self.update_nz(self.A)

    def _lsr(self, addr):
        val = self.read(addr)
        self.C = bool(val & 0x01)
        val = val >> 1
        self.write(addr, val)
        self.update_nz(val)

    def _lsr_a(self):
        self.C = bool(self.A & 0x01)
        self.A = self.A >> 1
        self.update_nz(self.A)

    def _rol(self, addr):
        val = self.read(addr)
        new_carry = bool(val & 0x80)
        val = (val << 1) & 0xFF
        self.C = new_carry
        if self.C:
            val |= 0x01
        self.write(addr, val)
        self.update_nz(val)

    def _rol_a(self):
        new_carry = bool(self.A & 0x80)
        self.A = (self.A << 1) & 0xFF
        self.C = new_carry
        if self.C:
            self.A |= 0x01
        self.update_nz(self.A)

    def _ror(self, addr):
        val = self.read(addr)
        old_carry = self.C
        self.C = bool(val & 0x01)
        val = val >> 1
        if old_carry:
            val |= 0x80
        self.write(addr, val)
        self.update_nz(val)

    def _ror_a(self):
        old_carry = self.C
        self.C = bool(self.A & 0x01)
        self.A = self.A >> 1
        if old_carry:
            self.A |= 0x80
        self.update_nz(self.A)

    def _bit(self, addr):
        val = self.read(addr)
        self.N = bool(val & 0x80)
        self.V = bool(val & 0x40)
        self.Z = (self.A & val) == 0

    def _jmp(self, addr):
        self.PC = addr

    def _jsr(self):
        addr = self.read16(self.PC)
        self.push16((self.PC + 1) & 0xFFFF)
        self.PC = addr

    def _rts(self):
        self.PC = (self.pull16() + 1) & 0xFFFF

    def _brk(self):
        self.push16(self.PC)
        self.push(self.get_status_byte(brk=True))
        self.I = True
        self.PC = self.read16(0xFFFE)

    def _pha(self):
        self.push(self.A)

    def _php(self):
        self.push(self.get_status_byte(brk=True))

    def _pla(self):
        self.A = self.pull()
        self.update_nz(self.A)

    def _plp(self):
        self.set_status_byte(self.pull())

    def _tax(self):
        self.X = self.A
        self.update_nz(self.X)

    def _tay(self):
        self.Y = self.A
        self.update_nz(self.Y)

    def _txa(self):
        self.A = self.X
        self.update_nz(self.A)

    def _tya(self):
        self.A = self.Y
        self.update_nz(self.A)

    def _tsx(self):
        self.X = self.SP
        self.update_nz(self.X)

    def _txs(self):
        self.SP = self.X

    def _inx(self):
        self.X = (self.X + 1) & 0xFF
        self.update_nz(self.X)

    def _iny(self):
        self.Y = (self.Y + 1) & 0xFF
        self.update_nz(self.Y)

    def _dex(self):
        self.X = (self.X - 1) & 0xFF
        self.update_nz(self.X)

    def _dey(self):
        self.Y = (self.Y - 1) & 0xFF
        self.update_nz(self.Y)

    # ---- Main dispatch ----

    def step(self):
        """Execute a single instruction."""
        opcode = self.read(self.PC)
        self.PC = (self.PC + 1) & 0xFFFF

        if opcode == 0x00:
            self._brk()
        elif opcode == 0x01:
            self._ora(self._izx())
        elif opcode == 0x05:
            self._ora(self._zp())
        elif opcode == 0x06:
            self._asl(self._zp())
        elif opcode == 0x08:
            self._php()
        elif opcode == 0x09:
            self._ora(self._imm())
        elif opcode == 0x0A:
            self._asl_a()
        elif opcode == 0x0D:
            self._ora(self._abs())
        elif opcode == 0x0E:
            self._asl(self._abs())
        elif opcode == 0x10:
            target = self._rel()
            if not self.N:
                self.PC = target
        elif opcode == 0x11:
            self._ora(self._izy())
        elif opcode == 0x15:
            self._ora(self._zpx())
        elif opcode == 0x16:
            self._asl(self._zpx())
        elif opcode == 0x18:
            self.C = False
        elif opcode == 0x19:
            self._ora(self._aby())
        elif opcode == 0x1D:
            self._ora(self._abx())
        elif opcode == 0x1E:
            self._asl(self._abx())
        elif opcode == 0x20:
            self._jsr()
        elif opcode == 0x21:
            self._and(self._izx())
        elif opcode == 0x24:
            self._bit(self._zp())
        elif opcode == 0x25:
            self._and(self._zp())
        elif opcode == 0x26:
            self._rol(self._zp())
        elif opcode == 0x28:
            self._plp()
        elif opcode == 0x29:
            self._and(self._imm())
        elif opcode == 0x2A:
            self._rol_a()
        elif opcode == 0x2C:
            self._bit(self._abs())
        elif opcode == 0x2D:
            self._and(self._abs())
        elif opcode == 0x2E:
            self._rol(self._abs())
        elif opcode == 0x30:
            target = self._rel()
            if self.N:
                self.PC = target
        elif opcode == 0x31:
            self._and(self._izy())
        elif opcode == 0x35:
            self._and(self._zpx())
        elif opcode == 0x36:
            self._rol(self._zpx())
        elif opcode == 0x38:
            self.C = True
        elif opcode == 0x39:
            self._and(self._aby())
        elif opcode == 0x3D:
            self._and(self._abx())
        elif opcode == 0x3E:
            self._rol(self._abx())
        elif opcode == 0x41:
            self._eor(self._izx())
        elif opcode == 0x45:
            self._eor(self._zp())
        elif opcode == 0x46:
            self._lsr(self._zp())
        elif opcode == 0x48:
            self._pha()
        elif opcode == 0x49:
            self._eor(self._imm())
        elif opcode == 0x4A:
            self._lsr_a()
        elif opcode == 0x4C:
            self._jmp(self._abs())
        elif opcode == 0x4D:
            self._eor(self._abs())
        elif opcode == 0x4E:
            self._lsr(self._abs())
        elif opcode == 0x50:
            target = self._rel()
            if not self.V:
                self.PC = target
        elif opcode == 0x51:
            self._eor(self._izy())
        elif opcode == 0x55:
            self._eor(self._zpx())
        elif opcode == 0x56:
            self._lsr(self._zpx())
        elif opcode == 0x58:
            self.I = False
        elif opcode == 0x59:
            self._eor(self._aby())
        elif opcode == 0x5D:
            self._eor(self._abx())
        elif opcode == 0x5E:
            self._lsr(self._abx())
        elif opcode == 0x60:
            self._rts()
        elif opcode == 0x61:
            self._adc(self._izx())
        elif opcode == 0x65:
            self._adc(self._zp())
        elif opcode == 0x66:
            self._ror(self._zp())
        elif opcode == 0x68:
            self._pla()
        elif opcode == 0x69:
            self._adc(self._imm())
        elif opcode == 0x6A:
            self._ror_a()
        elif opcode == 0x6C:
            self._jmp(self._ind())
        elif opcode == 0x6D:
            self._adc(self._abs())
        elif opcode == 0x6E:
            self._ror(self._abs())
        elif opcode == 0x70:
            target = self._rel()
            if self.V:
                self.PC = target
        elif opcode == 0x71:
            self._adc(self._izy())
        elif opcode == 0x75:
            self._adc(self._zpx())
        elif opcode == 0x76:
            self._ror(self._zpx())
        elif opcode == 0x78:
            self.I = True
        elif opcode == 0x79:
            self._adc(self._aby())
        elif opcode == 0x7D:
            self._adc(self._abx())
        elif opcode == 0x7E:
            self._ror(self._abx())
        elif opcode == 0x81:
            self._sta(self._izx())
        elif opcode == 0x84:
            self._sty(self._zp())
        elif opcode == 0x85:
            self._sta(self._zp())
        elif opcode == 0x86:
            self._stx(self._zp())
        elif opcode == 0x88:
            self._dey()
        elif opcode == 0x8A:
            self._txa()
        elif opcode == 0x8C:
            self._sty(self._abs())
        elif opcode == 0x8D:
            self._sta(self._abs())
        elif opcode == 0x8E:
            self._stx(self._abs())
        elif opcode == 0x90:
            target = self._rel()
            if not self.C:
                self.PC = target
        elif opcode == 0x91:
            self._sta(self._izy())
        elif opcode == 0x94:
            self._sty(self._zpx())
        elif opcode == 0x95:
            self._sta(self._zpx())
        elif opcode == 0x96:
            self._stx(self._zpy())
        elif opcode == 0x98:
            self._tya()
        elif opcode == 0x99:
            self._sta(self._aby())
        elif opcode == 0x9A:
            self._txs()
        elif opcode == 0x9D:
            self._sta(self._abx())
        elif opcode == 0xA0:
            self._ldy(self._imm())
        elif opcode == 0xA1:
            self._lda(self._izx())
        elif opcode == 0xA2:
            self._ldx(self._imm())
        elif opcode == 0xA4:
            self._ldy(self._zp())
        elif opcode == 0xA5:
            self._lda(self._zp())
        elif opcode == 0xA6:
            self._ldx(self._zp())
        elif opcode == 0xA8:
            self._tay()
        elif opcode == 0xA9:
            self._lda(self._imm())
        elif opcode == 0xAA:
            self._tax()
        elif opcode == 0xAC:
            self._ldy(self._abs())
        elif opcode == 0xAD:
            self._lda(self._abs())
        elif opcode == 0xAE:
            self._ldx(self._abs())
        elif opcode == 0xB0:
            target = self._rel()
            if self.C:
                self.PC = target
        elif opcode == 0xB1:
            self._lda(self._izy())
        elif opcode == 0xB4:
            self._ldy(self._zpx())
        elif opcode == 0xB5:
            self._lda(self._zpx())
        elif opcode == 0xB6:
            self._ldx(self._zpy())
        elif opcode == 0xB8:
            self.V = False
        elif opcode == 0xB9:
            self._lda(self._aby())
        elif opcode == 0xBA:
            self._tsx()
        elif opcode == 0xBC:
            self._ldy(self._abx())
        elif opcode == 0xBD:
            self._lda(self._abx())
        elif opcode == 0xBE:
            self._ldx(self._aby())
        elif opcode == 0xC0:
            self._cpy(self._imm())
        elif opcode == 0xC1:
            self._cmp(self._izx())
        elif opcode == 0xC4:
            self._cpy(self._zp())
        elif opcode == 0xC5:
            self._cmp(self._zp())
        elif opcode == 0xC6:
            self._dec(self._zp())
        elif opcode == 0xC8:
            self._iny()
        elif opcode == 0xC9:
            self._cmp(self._imm())
        elif opcode == 0xCA:
            self._dex()
        elif opcode == 0xCC:
            self._cpy(self._abs())
        elif opcode == 0xCD:
            self._cmp(self._abs())
        elif opcode == 0xCE:
            self._dec(self._abs())
        elif opcode == 0xD0:
            target = self._rel()
            if not self.Z:
                self.PC = target
        elif opcode == 0xD1:
            self._cmp(self._izy())
        elif opcode == 0xD5:
            self._cmp(self._zpx())
        elif opcode == 0xD6:
            self._dec(self._zpx())
        elif opcode == 0xD8:
            self.D = False
        elif opcode == 0xD9:
            self._cmp(self._aby())
        elif opcode == 0xDD:
            self._cmp(self._abx())
        elif opcode == 0xDE:
            self._dec(self._abx())
        elif opcode == 0xE0:
            self._cpx(self._imm())
        elif opcode == 0xE1:
            self._sbc(self._izx())
        elif opcode == 0xE4:
            self._cpx(self._zp())
        elif opcode == 0xE5:
            self._sbc(self._zp())
        elif opcode == 0xE6:
            self._inc(self._zp())
        elif opcode == 0xE8:
            self._inx()
        elif opcode == 0xE9:
            self._sbc(self._imm())
        elif opcode == 0xEA:
            pass  # NOP
        elif opcode == 0xEC:
            self._cpx(self._abs())
        elif opcode == 0xED:
            self._sbc(self._abs())
        elif opcode == 0xEE:
            self._inc(self._abs())
        elif opcode == 0xF0:
            target = self._rel()
            if self.Z:
                self.PC = target
        elif opcode == 0xF1:
            self._sbc(self._izy())
        elif opcode == 0xF5:
            self._sbc(self._zpx())
        elif opcode == 0xF6:
            self._inc(self._zpx())
        elif opcode == 0xF8:
            self.D = True
        elif opcode == 0xF9:
            self._sbc(self._aby())
        elif opcode == 0xFD:
            self._sbc(self._abx())
        elif opcode == 0xFE:
            self._inc(self._abx())
