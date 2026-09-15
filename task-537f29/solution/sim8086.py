#!/usr/bin/env python3
"""Intel 8086 CPU Simulator — decodes raw binary and simulates execution."""

import argparse
import sys


class CPU8086:
    # Register indices matching 8086 encoding: AX=0 CX=1 DX=2 BX=3 SP=4 BP=5 SI=6 DI=7
    AX, CX, DX, BX, SP, BP, SI, DI = range(8)
    # Flag bit positions
    CF, PF, AF, ZF, SF, OF = 0, 2, 4, 6, 7, 11

    def __init__(self):
        self.regs = [0] * 8
        self.ip = 0
        self.flags = 0
        self.memory = bytearray(1 << 20)  # 1 MB
        self.program_len = 0

    # ---- register helpers ----
    def gr16(self, i):
        return self.regs[i]

    def sr16(self, i, v):
        self.regs[i] = v & 0xFFFF

    def gr8(self, i):
        return (self.regs[i & 3] >> (8 * (i >> 2))) & 0xFF

    def sr8(self, i, v):
        r = i & 3
        if i < 4:
            self.regs[r] = (self.regs[r] & 0xFF00) | (v & 0xFF)
        else:
            self.regs[r] = (self.regs[r] & 0x00FF) | ((v & 0xFF) << 8)

    # ---- flag helpers ----
    def gf(self, b):
        return (self.flags >> b) & 1

    def sf(self, b, v):
        if v:
            self.flags |= 1 << b
        else:
            self.flags &= ~(1 << b)

    @staticmethod
    def _parity(v):
        v = v & 0xFF
        return 1 if bin(v).count("1") % 2 == 0 else 0

    # ---- memory helpers ----
    def rm8(self, a):
        return self.memory[a & 0xFFFFF]

    def rm16(self, a):
        a &= 0xFFFFF
        return self.memory[a] | (self.memory[(a + 1) & 0xFFFFF] << 8)

    def wm8(self, a, v):
        self.memory[a & 0xFFFFF] = v & 0xFF

    def wm16(self, a, v):
        a &= 0xFFFFF
        self.memory[a] = v & 0xFF
        self.memory[(a + 1) & 0xFFFFF] = (v >> 8) & 0xFF

    def fetch8(self):
        v = self.rm8(self.ip)
        self.ip = (self.ip + 1) & 0xFFFF
        return v

    def fetch16(self):
        v = self.rm16(self.ip)
        self.ip = (self.ip + 2) & 0xFFFF
        return v

    # ---- flag updates ----
    def _arith_flags(self, res, a, b, w, sub):
        mask = 0xFFFF if w else 0xFF
        sb = 15 if w else 7
        rm = res & mask
        self.sf(self.ZF, rm == 0)
        self.sf(self.SF, (rm >> sb) & 1)
        self.sf(self.PF, self._parity(rm))
        sa, sb2, sr = (a >> sb) & 1, (b >> sb) & 1, (rm >> sb) & 1
        if sub:
            self.sf(self.CF, (a & mask) < (b & mask))
            self.sf(self.OF, sa != sb2 and sr != sa)
            self.sf(self.AF, (a & 0xF) < (b & 0xF))
        else:
            self.sf(self.CF, res > mask)
            self.sf(self.OF, sa == sb2 and sr != sa)
            self.sf(self.AF, ((a & 0xF) + (b & 0xF)) > 0xF)
        return rm

    def _logic_flags(self, res, w):
        mask = 0xFFFF if w else 0xFF
        sb = 15 if w else 7
        rm = res & mask
        self.sf(self.CF, 0)
        self.sf(self.OF, 0)
        self.sf(self.ZF, rm == 0)
        self.sf(self.SF, (rm >> sb) & 1)
        self.sf(self.PF, self._parity(rm))
        return rm

    # ---- MOD/REG/RM decoder ----
    def _ea_base(self, rm_field):
        t = [
            lambda: self.gr16(self.BX) + self.gr16(self.SI),
            lambda: self.gr16(self.BX) + self.gr16(self.DI),
            lambda: self.gr16(self.BP) + self.gr16(self.SI),
            lambda: self.gr16(self.BP) + self.gr16(self.DI),
            lambda: self.gr16(self.SI),
            lambda: self.gr16(self.DI),
            lambda: self.gr16(self.BP),
            lambda: self.gr16(self.BX),
        ]
        return t[rm_field]()

    def decode_modrm(self, modrm, w):
        """Returns (reg_field, rm_val, ea_or_None, rm_idx)."""
        mod = (modrm >> 6) & 3
        reg = (modrm >> 3) & 7
        rm = modrm & 7
        if mod == 3:
            return reg, (self.gr16(rm) if w else self.gr8(rm)), None, rm
        if mod == 0 and rm == 6:
            ea = self.fetch16()
        else:
            ea = self._ea_base(rm)
            if mod == 1:
                d = self.fetch8()
                ea += d - 256 if d & 0x80 else d
            elif mod == 2:
                d = self.fetch16()
                ea += d - 65536 if d & 0x8000 else d
        ea &= 0xFFFF
        return reg, (self.rm16(ea) if w else self.rm8(ea)), ea, rm

    def write_rm(self, ea, rm, w, val):
        if ea is not None:
            (self.wm16 if w else self.wm8)(ea, val)
        else:
            (self.sr16 if w else self.sr8)(rm, val)

    # ---- ALU core ----
    def _alu(self, op, dst, src, w):
        mask = 0xFFFF if w else 0xFF
        d, s = dst & mask, src & mask
        if op == 0:  # ADD
            r = d + s
            self._arith_flags(r, d, s, w, False)
            return r & mask
        if op == 5 or op == 7:  # SUB / CMP
            r = d - s
            self._arith_flags(r, d, s, w, True)
            return r & mask
        if op == 4:  # AND
            return self._logic_flags(d & s, w)
        if op == 1:  # OR
            return self._logic_flags(d | s, w)
        if op == 6:  # XOR
            return self._logic_flags(d ^ s, w)
        if op == 2:  # ADC
            cf = self.gf(self.CF)
            r = d + s + cf
            self._arith_flags(r, d, s + cf, w, False)
            return r & mask
        if op == 3:  # SBB
            cf = self.gf(self.CF)
            r = d - s - cf
            self._arith_flags(r, d, s + cf, w, True)
            return r & mask
        raise ValueError(f"Unknown ALU op {op}")

    # ---- load / run ----
    def load(self, data):
        for i, b in enumerate(data):
            self.memory[i] = b
        self.program_len = len(data)

    def run(self, limit=10_000_000):
        for _ in range(limit):
            if self.ip >= self.program_len:
                return
            self._step()

    # ---- main instruction dispatcher ----
    def _step(self):  # noqa: C901 — deliberately monolithic for perf
        op = self.fetch8()

        # --- MOV reg, imm (short) B0-BF ---
        if 0xB0 <= op <= 0xBF:
            w = (op >> 3) & 1
            reg = op & 7
            if w:
                self.sr16(reg, self.fetch16())
            else:
                self.sr8(reg, self.fetch8())
            return

        # --- INC reg16 40-47 ---
        if 0x40 <= op <= 0x47:
            r = op - 0x40
            v = self.gr16(r)
            res = v + 1
            cf = self.gf(self.CF)
            self._arith_flags(res, v, 1, 1, False)
            self.sf(self.CF, cf)
            self.sr16(r, res & 0xFFFF)
            return

        # --- DEC reg16 48-4F ---
        if 0x48 <= op <= 0x4F:
            r = op - 0x48
            v = self.gr16(r)
            res = v - 1
            cf = self.gf(self.CF)
            self._arith_flags(res, v, 1, 1, True)
            self.sf(self.CF, cf)
            self.sr16(r, res & 0xFFFF)
            return

        # --- XCHG AX, reg 90-97 ---
        if 0x90 <= op <= 0x97:
            r = op - 0x90
            if r == 0:
                return  # NOP
            t = self.gr16(0)
            self.sr16(0, self.gr16(r))
            self.sr16(r, t)
            return

        # --- General reg/rm ALU 00-3B ---
        ALU_LUT = {
            0x00: (0, 0, 0), 0x01: (0, 1, 0), 0x02: (0, 0, 1), 0x03: (0, 1, 1),
            0x08: (1, 0, 0), 0x09: (1, 1, 0), 0x0A: (1, 0, 1), 0x0B: (1, 1, 1),
            0x10: (2, 0, 0), 0x11: (2, 1, 0), 0x12: (2, 0, 1), 0x13: (2, 1, 1),
            0x18: (3, 0, 0), 0x19: (3, 1, 0), 0x1A: (3, 0, 1), 0x1B: (3, 1, 1),
            0x20: (4, 0, 0), 0x21: (4, 1, 0), 0x22: (4, 0, 1), 0x23: (4, 1, 1),
            0x28: (5, 0, 0), 0x29: (5, 1, 0), 0x2A: (5, 0, 1), 0x2B: (5, 1, 1),
            0x30: (6, 0, 0), 0x31: (6, 1, 0), 0x32: (6, 0, 1), 0x33: (6, 1, 1),
            0x38: (7, 0, 0), 0x39: (7, 1, 0), 0x3A: (7, 0, 1), 0x3B: (7, 1, 1),
        }
        if op in ALU_LUT:
            alu_op, w, d = ALU_LUT[op]
            modrm = self.fetch8()
            reg_f, rm_v, ea, rm_i = self.decode_modrm(modrm, w)
            rv = self.gr16(reg_f) if w else self.gr8(reg_f)
            if d == 0:
                res = self._alu(alu_op, rm_v, rv, w)
                if alu_op != 7:
                    self.write_rm(ea, rm_i, w, res)
            else:
                res = self._alu(alu_op, rv, rm_v, w)
                if alu_op != 7:
                    (self.sr16 if w else self.sr8)(reg_f, res)
            return

        # --- Acc immediate ALU 04/05 .. 3C/3D ---
        ACC_IMM = {
            0x04: (0, 0), 0x05: (0, 1), 0x0C: (1, 0), 0x0D: (1, 1),
            0x14: (2, 0), 0x15: (2, 1), 0x1C: (3, 0), 0x1D: (3, 1),
            0x24: (4, 0), 0x25: (4, 1), 0x2C: (5, 0), 0x2D: (5, 1),
            0x34: (6, 0), 0x35: (6, 1), 0x3C: (7, 0), 0x3D: (7, 1),
        }
        if op in ACC_IMM:
            alu_op, w = ACC_IMM[op]
            imm = self.fetch16() if w else self.fetch8()
            acc = self.gr16(0) if w else self.gr8(0)
            res = self._alu(alu_op, acc, imm, w)
            if alu_op != 7:
                (self.sr16 if w else self.sr8)(0, res)
            return

        # --- Immediate group 80-83 ---
        if op in (0x80, 0x81, 0x82, 0x83):
            w = op & 1
            modrm = self.fetch8()
            reg_f, rm_v, ea, rm_i = self.decode_modrm(modrm, w)
            if op == 0x81:
                imm = self.fetch16()
            elif op == 0x83:
                imm = self.fetch8()
                if imm & 0x80:
                    imm |= 0xFF00
            else:
                imm = self.fetch8()
            res = self._alu(reg_f, rm_v, imm, w)
            if reg_f != 7:  # not CMP
                self.write_rm(ea, rm_i, w, res)
            return

        # --- MOV reg/rm 88-8B ---
        if 0x88 <= op <= 0x8B:
            w = op & 1
            d = (op >> 1) & 1
            modrm = self.fetch8()
            reg_f, rm_v, ea, rm_i = self.decode_modrm(modrm, w)
            if d == 0:
                v = self.gr16(reg_f) if w else self.gr8(reg_f)
                self.write_rm(ea, rm_i, w, v)
            else:
                (self.sr16 if w else self.sr8)(reg_f, rm_v)
            return

        # --- MOV imm to r/m C6/C7 ---
        if op in (0xC6, 0xC7):
            w = op & 1
            modrm = self.fetch8()
            _, _, ea, rm_i = self.decode_modrm(modrm, w)
            imm = self.fetch16() if w else self.fetch8()
            self.write_rm(ea, rm_i, w, imm)
            return

        # --- MOV acc/mem A0-A3 ---
        if 0xA0 <= op <= 0xA3:
            w = op & 1
            addr = self.fetch16()
            if op <= 0xA1:
                (self.sr16 if w else self.sr8)(0, self.rm16(addr) if w else self.rm8(addr))
            else:
                (self.wm16 if w else self.wm8)(addr, self.gr16(0) if w else self.gr8(0))
            return

        # --- Unary group F6/F7 ---
        if op in (0xF6, 0xF7):
            w = op & 1
            modrm = self.fetch8()
            reg_f, rm_v, ea, rm_i = self.decode_modrm(modrm, w)
            mask = 0xFFFF if w else 0xFF
            if reg_f == 0:  # TEST r/m, imm
                imm = self.fetch16() if w else self.fetch8()
                self._logic_flags(rm_v & imm, w)
            elif reg_f == 2:  # NOT
                self.write_rm(ea, rm_i, w, (~rm_v) & mask)
            elif reg_f == 3:  # NEG
                res = (-rm_v) & mask
                self._arith_flags(0 - rm_v, 0, rm_v, w, True)
                self.sf(self.CF, 0 if rm_v == 0 else 1)
                self.write_rm(ea, rm_i, w, res)
            elif reg_f == 4:  # MUL
                if w:
                    r = self.gr16(0) * rm_v
                    self.sr16(0, r & 0xFFFF)
                    self.sr16(self.DX, (r >> 16) & 0xFFFF)
                    ov = int(self.gr16(self.DX) != 0)
                    self.sf(self.CF, ov)
                    self.sf(self.OF, ov)
                else:
                    r = self.gr8(0) * rm_v
                    self.sr16(0, r & 0xFFFF)
                    ov = int((r >> 8) != 0)
                    self.sf(self.CF, ov)
                    self.sf(self.OF, ov)
            elif reg_f == 5:  # IMUL
                if w:
                    a = self.gr16(0)
                    if a >= 0x8000:
                        a -= 0x10000
                    b = rm_v
                    if b >= 0x8000:
                        b -= 0x10000
                    r = a * b
                    self.sr16(0, r & 0xFFFF)
                    self.sr16(self.DX, (r >> 16) & 0xFFFF)
                else:
                    a = self.gr8(0)
                    if a >= 0x80:
                        a -= 0x100
                    b = rm_v
                    if b >= 0x80:
                        b -= 0x100
                    r = a * b
                    self.sr16(0, r & 0xFFFF)
            elif reg_f == 6:  # DIV
                if w:
                    dividend = (self.gr16(self.DX) << 16) | self.gr16(0)
                    self.sr16(0, dividend // rm_v)
                    self.sr16(self.DX, dividend % rm_v)
                else:
                    dividend = self.gr16(0)
                    self.sr8(0, dividend // rm_v)
                    self.sr8(4, dividend % rm_v)
            elif reg_f == 7:  # IDIV
                if w:
                    dividend = (self.gr16(self.DX) << 16) | self.gr16(0)
                    if dividend >= 0x80000000:
                        dividend -= 0x100000000
                    divisor = rm_v
                    if divisor >= 0x8000:
                        divisor -= 0x10000
                    q = int(dividend / divisor)
                    r2 = dividend - q * divisor
                    self.sr16(0, q & 0xFFFF)
                    self.sr16(self.DX, r2 & 0xFFFF)
            return

        # --- Shift/rotate D0-D3 ---
        if op in (0xD0, 0xD1, 0xD2, 0xD3):
            w = op & 1
            by_cl = (op >> 1) & 1
            modrm = self.fetch8()
            reg_f, rm_v, ea, rm_i = self.decode_modrm(modrm, w)
            mask = 0xFFFF if w else 0xFF
            sb = 15 if w else 7
            count = self.gr8(1) if by_cl else 1  # CL or 1
            res = rm_v
            for _ in range(count):
                if reg_f == 4:  # SHL
                    self.sf(self.CF, (res >> sb) & 1)
                    res = (res << 1) & mask
                elif reg_f == 5:  # SHR
                    self.sf(self.CF, res & 1)
                    res >>= 1
                elif reg_f == 7:  # SAR
                    self.sf(self.CF, res & 1)
                    sign = res & (1 << sb)
                    res = (res >> 1) | sign
                elif reg_f == 0:  # ROL
                    hi = (res >> sb) & 1
                    res = ((res << 1) | hi) & mask
                    self.sf(self.CF, hi)
                elif reg_f == 1:  # ROR
                    lo = res & 1
                    res = (res >> 1) | (lo << sb)
                    self.sf(self.CF, lo)
                elif reg_f == 2:  # RCL
                    cf = self.gf(self.CF)
                    hi = (res >> sb) & 1
                    res = ((res << 1) | cf) & mask
                    self.sf(self.CF, hi)
                elif reg_f == 3:  # RCR
                    cf = self.gf(self.CF)
                    lo = res & 1
                    res = (res >> 1) | (cf << sb)
                    self.sf(self.CF, lo)
            self.sf(self.ZF, res == 0)
            self.sf(self.SF, (res >> sb) & 1)
            self.sf(self.PF, self._parity(res))
            self.write_rm(ea, rm_i, w, res)
            return

        # --- Conditional jumps 70-7F ---
        COND = {
            0x70: lambda s: s.gf(s.OF),
            0x71: lambda s: not s.gf(s.OF),
            0x72: lambda s: s.gf(s.CF),
            0x73: lambda s: not s.gf(s.CF),
            0x74: lambda s: s.gf(s.ZF),
            0x75: lambda s: not s.gf(s.ZF),
            0x76: lambda s: s.gf(s.CF) or s.gf(s.ZF),
            0x77: lambda s: not s.gf(s.CF) and not s.gf(s.ZF),
            0x78: lambda s: s.gf(s.SF),
            0x79: lambda s: not s.gf(s.SF),
            0x7A: lambda s: s.gf(s.PF),
            0x7B: lambda s: not s.gf(s.PF),
            0x7C: lambda s: s.gf(s.SF) != s.gf(s.OF),
            0x7D: lambda s: s.gf(s.SF) == s.gf(s.OF),
            0x7E: lambda s: s.gf(s.ZF) or s.gf(s.SF) != s.gf(s.OF),
            0x7F: lambda s: not s.gf(s.ZF) and s.gf(s.SF) == s.gf(s.OF),
        }
        if op in COND:
            off = self.fetch8()
            if off & 0x80:
                off -= 256
            if COND[op](self):
                self.ip = (self.ip + off) & 0xFFFF
            return

        # --- LOOP E0-E2, JCXZ E3 ---
        if 0xE0 <= op <= 0xE3:
            off = self.fetch8()
            if off & 0x80:
                off -= 256
            if op == 0xE3:  # JCXZ
                if self.gr16(self.CX) == 0:
                    self.ip = (self.ip + off) & 0xFFFF
                return
            cx = (self.gr16(self.CX) - 1) & 0xFFFF
            self.sr16(self.CX, cx)
            jump = False
            if op == 0xE2:
                jump = cx != 0
            elif op == 0xE1:
                jump = cx != 0 and self.gf(self.ZF)
            elif op == 0xE0:
                jump = cx != 0 and not self.gf(self.ZF)
            if jump:
                self.ip = (self.ip + off) & 0xFFFF
            return

        # --- TEST r/m, r 84/85 ---
        if op in (0x84, 0x85):
            w = op & 1
            modrm = self.fetch8()
            reg_f, rm_v, ea, rm_i = self.decode_modrm(modrm, w)
            rv = self.gr16(reg_f) if w else self.gr8(reg_f)
            self._logic_flags(rm_v & rv, w)
            return

        # --- TEST acc, imm A8/A9 ---
        if op in (0xA8, 0xA9):
            w = op & 1
            imm = self.fetch16() if w else self.fetch8()
            acc = self.gr16(0) if w else self.gr8(0)
            self._logic_flags(acc & imm, w)
            return

        # --- LEA 8D ---
        if op == 0x8D:
            modrm = self.fetch8()
            mod = (modrm >> 6) & 3
            reg = (modrm >> 3) & 7
            rm = modrm & 7
            if mod == 0 and rm == 6:
                ea = self.fetch16()
            else:
                ea = self._ea_base(rm)
                if mod == 1:
                    d = self.fetch8()
                    ea += d - 256 if d & 0x80 else d
                elif mod == 2:
                    d = self.fetch16()
                    ea += d - 65536 if d & 0x8000 else d
            self.sr16(reg, ea & 0xFFFF)
            return

        # --- XCHG r/m, r 86/87 ---
        if op in (0x86, 0x87):
            w = op & 1
            modrm = self.fetch8()
            reg_f, rm_v, ea, rm_i = self.decode_modrm(modrm, w)
            rv = self.gr16(reg_f) if w else self.gr8(reg_f)
            (self.sr16 if w else self.sr8)(reg_f, rm_v)
            self.write_rm(ea, rm_i, w, rv)
            return

        # --- PUSH reg16 50-57 ---
        if 0x50 <= op <= 0x57:
            r = op - 0x50
            sp = (self.gr16(self.SP) - 2) & 0xFFFF
            self.sr16(self.SP, sp)
            self.wm16(sp, self.gr16(r))
            return

        # --- POP reg16 58-5F ---
        if 0x58 <= op <= 0x5F:
            r = op - 0x58
            sp = self.gr16(self.SP)
            self.sr16(r, self.rm16(sp))
            self.sr16(self.SP, (sp + 2) & 0xFFFF)
            return

        # --- PUSH r/m FF /6 and INC/DEC r/m FF /0 /1 ---
        if op == 0xFF:
            modrm = self.fetch8()
            reg_f, rm_v, ea, rm_i = self.decode_modrm(modrm, 1)
            if reg_f == 6:  # PUSH r/m16
                sp = (self.gr16(self.SP) - 2) & 0xFFFF
                self.sr16(self.SP, sp)
                self.wm16(sp, rm_v)
            elif reg_f == 0:  # INC r/m16
                res = rm_v + 1
                cf = self.gf(self.CF)
                self._arith_flags(res, rm_v, 1, 1, False)
                self.sf(self.CF, cf)
                self.write_rm(ea, rm_i, 1, res & 0xFFFF)
            elif reg_f == 1:  # DEC r/m16
                res = rm_v - 1
                cf = self.gf(self.CF)
                self._arith_flags(res, rm_v, 1, 1, True)
                self.sf(self.CF, cf)
                self.write_rm(ea, rm_i, 1, res & 0xFFFF)
            elif reg_f == 4:  # JMP r/m16
                self.ip = rm_v
            elif reg_f == 2:  # CALL r/m16
                sp = (self.gr16(self.SP) - 2) & 0xFFFF
                self.sr16(self.SP, sp)
                self.wm16(sp, self.ip)
                self.ip = rm_v
            return

        # --- INC/DEC r/m8 FE ---
        if op == 0xFE:
            modrm = self.fetch8()
            reg_f, rm_v, ea, rm_i = self.decode_modrm(modrm, 0)
            if reg_f == 0:  # INC r/m8
                res = rm_v + 1
                cf = self.gf(self.CF)
                self._arith_flags(res, rm_v, 1, 0, False)
                self.sf(self.CF, cf)
                self.write_rm(ea, rm_i, 0, res & 0xFF)
            elif reg_f == 1:  # DEC r/m8
                res = rm_v - 1
                cf = self.gf(self.CF)
                self._arith_flags(res, rm_v, 1, 0, True)
                self.sf(self.CF, cf)
                self.write_rm(ea, rm_i, 0, res & 0xFF)
            return

        # --- JMP short EB ---
        if op == 0xEB:
            off = self.fetch8()
            if off & 0x80:
                off -= 256
            self.ip = (self.ip + off) & 0xFFFF
            return

        # --- JMP near E9 ---
        if op == 0xE9:
            off = self.fetch16()
            if off & 0x8000:
                off -= 65536
            self.ip = (self.ip + off) & 0xFFFF
            return

        # --- CALL near E8 ---
        if op == 0xE8:
            off = self.fetch16()
            if off & 0x8000:
                off -= 65536
            sp = (self.gr16(self.SP) - 2) & 0xFFFF
            self.sr16(self.SP, sp)
            self.wm16(sp, self.ip)
            self.ip = (self.ip + off) & 0xFFFF
            return

        # --- RET near C3 ---
        if op == 0xC3:
            sp = self.gr16(self.SP)
            self.ip = self.rm16(sp)
            self.sr16(self.SP, (sp + 2) & 0xFFFF)
            return

        # --- RET near imm16 C2 ---
        if op == 0xC2:
            imm = self.fetch16()
            sp = self.gr16(self.SP)
            self.ip = self.rm16(sp)
            self.sr16(self.SP, (sp + 2 + imm) & 0xFFFF)
            return

        # --- HLT F4 ---
        if op == 0xF4:
            self.ip = self.program_len
            return

        # --- Flag manipulation ---
        FLAG_OPS = {
            0xF8: (CPU8086.CF, 0), 0xF9: (CPU8086.CF, 1), 0xF5: (CPU8086.CF, -1),
            0xFC: (10, 0), 0xFD: (10, 1), 0xFA: (9, 0), 0xFB: (9, 1),
        }
        if op in FLAG_OPS:
            bit, val = FLAG_OPS[op]
            if val == -1:
                self.sf(bit, 1 - self.gf(bit))
            else:
                self.sf(bit, val)
            return

        # --- CBW 98 ---
        if op == 0x98:
            al = self.gr8(0)
            self.sr8(4, 0xFF if al & 0x80 else 0x00)
            return

        # --- CWD 99 ---
        if op == 0x99:
            ax = self.gr16(0)
            self.sr16(self.DX, 0xFFFF if ax & 0x8000 else 0x0000)
            return

        # --- Segment override prefixes (ignored) 26/2E/36/3E ---
        if op in (0x26, 0x2E, 0x36, 0x3E):
            self._step()
            return

        # --- LOCK prefix F0 (ignored) ---
        if op == 0xF0:
            self._step()
            return

        # --- REP/REPNE F2/F3 (ignored, just exec next) ---
        if op in (0xF2, 0xF3):
            self._step()
            return

        # --- MOV sr, r/m 8E  /  MOV r/m, sr 8C ---
        if op in (0x8C, 0x8E):
            modrm = self.fetch8()
            # Segment registers: ignore for simulation (no segments)
            _, rm_v, ea, rm_i = self.decode_modrm(modrm, 1)
            return

        # --- PUSH/POP segment regs 06/0E/16/1E/07/17/1F ---
        if op in (0x06, 0x0E, 0x16, 0x1E):
            sp = (self.gr16(self.SP) - 2) & 0xFFFF
            self.sr16(self.SP, sp)
            self.wm16(sp, 0)
            return
        if op in (0x07, 0x17, 0x1F):
            sp = self.gr16(self.SP)
            self.sr16(self.SP, (sp + 2) & 0xFFFF)
            return

        # --- LAHF 9F / SAHF 9E ---
        if op == 0x9F:
            self.sr8(4, self.flags & 0xFF)
            return
        if op == 0x9E:
            self.flags = (self.flags & 0xFF00) | self.gr8(4)
            return

        # --- PUSHF 9C / POPF 9D ---
        if op == 0x9C:
            sp = (self.gr16(self.SP) - 2) & 0xFFFF
            self.sr16(self.SP, sp)
            self.wm16(sp, self.flags)
            return
        if op == 0x9D:
            sp = self.gr16(self.SP)
            self.flags = self.rm16(sp)
            self.sr16(self.SP, (sp + 2) & 0xFFFF)
            return

        # --- LDS 0xC5 / LES 0xC4 (load far pointer, ignore segment) ---
        if op in (0xC4, 0xC5):
            modrm = self.fetch8()
            reg_f, rm_v, ea, rm_i = self.decode_modrm(modrm, 1)
            self.sr16(reg_f, rm_v)
            if ea is not None:
                self.rm16((ea + 2) & 0xFFFF)  # read segment, discard
            return

        # --- AAA 37 / AAS 3F / DAA 27 / DAS 2F / AAM D4 / AAD D5 ---
        if op in (0x27, 0x2F, 0x37, 0x3F):
            return  # BCD: noop in our sim
        if op in (0xD4, 0xD5):
            self.fetch8()  # skip imm8
            return

        # --- XLAT D7 ---
        if op == 0xD7:
            addr = (self.gr16(self.BX) + self.gr8(0)) & 0xFFFF
            self.sr8(0, self.rm8(addr))
            return

        # --- INT CC/CD, INTO CE, IRET CF ---
        if op == 0xCC:
            return
        if op == 0xCD:
            self.fetch8()
            return
        if op == 0xCE:
            return
        if op == 0xCF:
            return

        # --- IN E4/E5/EC/ED ---
        if op in (0xE4, 0xE5):
            self.fetch8()
            return
        if op in (0xEC, 0xED):
            return

        # --- OUT E6/E7/EE/EF ---
        if op in (0xE6, 0xE7):
            self.fetch8()
            return
        if op in (0xEE, 0xEF):
            return

        # --- WAIT 9B ---
        if op == 0x9B:
            return

        raise ValueError(f"Unknown opcode 0x{op:02X} at IP=0x{self.ip - 1:04X}")

    # ---- output ----
    def format_flags(self):
        s = ""
        if self.gf(self.CF):
            s += "C"
        if self.gf(self.ZF):
            s += "Z"
        if self.gf(self.SF):
            s += "S"
        if self.gf(self.OF):
            s += "O"
        if self.gf(self.PF):
            s += "P"
        if self.gf(self.AF):
            s += "A"
        return s

    def print_state(self, memdump=None):
        order = [
            (self.AX, "AX"), (self.BX, "BX"), (self.CX, "CX"), (self.DX, "DX"),
            (self.SP, "SP"), (self.BP, "BP"), (self.SI, "SI"), (self.DI, "DI"),
        ]
        for idx, name in order:
            print(f"{name}: 0x{self.regs[idx]:04X}")
        print(f"IP: 0x{self.ip:04X}")
        print(f"FLAGS: {self.format_flags()}")
        if memdump:
            addr, length = memdump
            bs = " ".join(f"{self.memory[(addr + i) & 0xFFFFF]:02X}" for i in range(length))
            print(f"MEM[0x{addr:04X}]: {bs}")


def main():
    parser = argparse.ArgumentParser(description="8086 CPU Simulator")
    parser.add_argument("binary", help="Raw 8086 binary file")
    parser.add_argument("--memdump", nargs=2, metavar=("ADDR", "LEN"),
                        help="Dump memory (ADDR in hex, LEN in decimal)")
    args = parser.parse_args()

    with open(args.binary, "rb") as f:
        data = f.read()

    cpu = CPU8086()
    cpu.load(data)
    cpu.run()

    md = None
    if args.memdump:
        md = (int(args.memdump[0], 0), int(args.memdump[1], 0))
    cpu.print_state(md)


if __name__ == "__main__":
    main()
