#!/usr/bin/env python3
"""
Intel 8086 CPU Simulator with cycle-accurate timing estimation.
"""
import sys
import argparse


# EA clock costs indexed by (mod, rm)
EA_CLOCKS = {
    (0, 0): 7,  (0, 1): 8,  (0, 2): 8,  (0, 3): 7,
    (0, 4): 5,  (0, 5): 5,  (0, 6): 6,  (0, 7): 5,
    (1, 0): 11, (1, 1): 12, (1, 2): 12, (1, 3): 11,
    (1, 4): 9,  (1, 5): 9,  (1, 6): 9,  (1, 7): 9,
    (2, 0): 11, (2, 1): 12, (2, 2): 12, (2, 3): 11,
    (2, 4): 9,  (2, 5): 9,  (2, 6): 9,  (2, 7): 9,
}


class CPU:
    R16 = ["ax", "cx", "dx", "bx", "sp", "bp", "si", "di"]
    R8_PARENT = ["ax", "cx", "dx", "bx", "ax", "cx", "dx", "bx"]

    def __init__(self):
        self.mem = bytearray(65536)
        self.regs = {r: 0 for r in self.R16}
        self.ip = 0
        self.flags = {f: False for f in ("CF", "PF", "AF", "ZF", "SF", "OF")}
        self.prog_end = 0
        # Cycle tracking
        self._base = 0
        self._ea = 0
        self._pen = 0
        self.total_cycles = 0
        self.cycle_log = []  # list of (ip_before, base, ea, pen, total)

    # ── register helpers ──

    def gr8(self, i):
        v = self.regs[self.R8_PARENT[i]]
        return v & 0xFF if i < 4 else (v >> 8) & 0xFF

    def sr8(self, i, v):
        v &= 0xFF
        p = self.R8_PARENT[i]
        if i < 4:
            self.regs[p] = (self.regs[p] & 0xFF00) | v
        else:
            self.regs[p] = (self.regs[p] & 0x00FF) | (v << 8)

    def gr16(self, i):
        return self.regs[self.R16[i]]

    def sr16(self, i, v):
        self.regs[self.R16[i]] = v & 0xFFFF

    # ── memory helpers ──

    def rb(self):
        b = self.mem[self.ip]
        self.ip += 1
        return b

    def rw(self):
        lo = self.mem[self.ip]
        hi = self.mem[self.ip + 1]
        self.ip += 2
        return lo | (hi << 8)

    def rm8(self, a):
        return self.mem[a & 0xFFFF]

    def wm8(self, a, v):
        self.mem[a & 0xFFFF] = v & 0xFF

    def rm16(self, a):
        a &= 0xFFFF
        return self.mem[a] | (self.mem[(a + 1) & 0xFFFF] << 8)

    def wm16(self, a, v):
        a &= 0xFFFF
        self.mem[a] = v & 0xFF
        self.mem[(a + 1) & 0xFFFF] = (v >> 8) & 0xFF

    # ── effective address ──

    def ea(self, mod, rm):
        if mod == 0 and rm == 6:
            return self.rw()
        bases = [
            self.regs["bx"] + self.regs["si"],
            self.regs["bx"] + self.regs["di"],
            self.regs["bp"] + self.regs["si"],
            self.regs["bp"] + self.regs["di"],
            self.regs["si"],
            self.regs["di"],
            self.regs["bp"],
            self.regs["bx"],
        ]
        a = bases[rm]
        if mod == 1:
            d = self.rb()
            if d > 127:
                d -= 256
            a += d
        elif mod == 2:
            d = self.rw()
            if d > 32767:
                d -= 65536
            a += d
        return a & 0xFFFF

    # ── cycle helpers ──

    def _add_ea(self, mod, rm):
        self._ea += EA_CLOCKS[(mod, rm)]

    def _add_penalty(self, addr, w):
        if w and (addr & 1):
            self._pen += 4

    # ── modrm decode ──

    def modrm(self):
        b = self.rb()
        return (b >> 6) & 3, (b >> 3) & 7, b & 7

    def resolve_rm(self, mod, rm, w):
        """Return (value, location, is_mem). location is reg index or address."""
        if mod == 3:
            return (self.gr16(rm) if w else self.gr8(rm)), rm, False
        addr = self.ea(mod, rm)
        return (self.rm16(addr) if w else self.rm8(addr)), addr, True

    def write_rm(self, loc, is_mem, w, v):
        if is_mem:
            if w:
                self.wm16(loc, v)
            else:
                self.wm8(loc, v)
        else:
            if w:
                self.sr16(loc, v)
            else:
                self.sr8(loc, v)

    # ── flag computation ──

    def uflags(self, res, a, b, w, sub):
        mask = 0xFFFF if w else 0xFF
        sb = 0x8000 if w else 0x80
        r = res & mask
        self.flags["ZF"] = r == 0
        self.flags["SF"] = bool(r & sb)
        self.flags["PF"] = bin(r & 0xFF).count("1") % 2 == 0
        if sub:
            self.flags["CF"] = (a & mask) < (b & mask)
        else:
            self.flags["CF"] = res > mask
        as_, bs, rs = bool(a & sb), bool(b & sb), bool(r & sb)
        if sub:
            self.flags["OF"] = (as_ != bs) and (rs != as_)
        else:
            self.flags["OF"] = (as_ == bs) and (rs != as_)
        if sub:
            self.flags["AF"] = (a & 0xF) < (b & 0xF)
        else:
            self.flags["AF"] = ((a & 0xF) + (b & 0xF)) > 0xF

    # ── ALU ──

    def alu(self, op, a, b, w):
        mask = 0xFFFF if w else 0xFF
        sb = 0x8000 if w else 0x80
        if op == 0:  # ADD
            r = a + b
            self.uflags(r, a, b, w, False)
            return r & mask
        elif op == 1:  # OR
            r = (a | b) & mask
            self.flags["CF"] = self.flags["OF"] = False
            self.flags["ZF"] = r == 0
            self.flags["SF"] = bool(r & sb)
            self.flags["PF"] = bin(r & 0xFF).count("1") % 2 == 0
            self.flags["AF"] = False
            return r
        elif op == 2:  # ADC
            c = 1 if self.flags["CF"] else 0
            r = a + b + c
            self.uflags(r, a, b + c, w, False)
            return r & mask
        elif op == 3:  # SBB
            c = 1 if self.flags["CF"] else 0
            r = a - b - c
            self.uflags(r, a, b + c, w, True)
            return r & mask
        elif op == 4:  # AND
            r = (a & b) & mask
            self.flags["CF"] = self.flags["OF"] = False
            self.flags["ZF"] = r == 0
            self.flags["SF"] = bool(r & sb)
            self.flags["PF"] = bin(r & 0xFF).count("1") % 2 == 0
            self.flags["AF"] = False
            return r
        elif op == 5:  # SUB
            r = a - b
            self.uflags(r, a, b, w, True)
            return r & mask
        elif op == 6:  # XOR
            r = (a ^ b) & mask
            self.flags["CF"] = self.flags["OF"] = False
            self.flags["ZF"] = r == 0
            self.flags["SF"] = bool(r & sb)
            self.flags["PF"] = bin(r & 0xFF).count("1") % 2 == 0
            self.flags["AF"] = False
            return r
        elif op == 7:  # CMP
            r = a - b
            self.uflags(r, a, b, w, True)
            return a  # CMP does not store

    # ── conditions ──

    def cond(self, c):
        f = self.flags
        tbl = [
            f["OF"],
            not f["OF"],
            f["CF"],
            not f["CF"],
            f["ZF"],
            not f["ZF"],
            f["CF"] or f["ZF"],
            not f["CF"] and not f["ZF"],
            f["SF"],
            not f["SF"],
            f["PF"],
            not f["PF"],
            f["SF"] != f["OF"],
            f["SF"] == f["OF"],
            f["ZF"] or (f["SF"] != f["OF"]),
            not f["ZF"] and (f["SF"] == f["OF"]),
        ]
        return tbl[c]

    # ── main dispatch ──

    def step(self):
        self._base = 0
        self._ea = 0
        self._pen = 0
        ip_before = self.ip

        op = self.rb()

        # --- MOV reg8, imm8 (B0-B7) ---
        if 0xB0 <= op <= 0xB7:
            self.sr8(op - 0xB0, self.rb())
            self._base = 4

        # --- MOV reg16, imm16 (B8-BF) ---
        elif 0xB8 <= op <= 0xBF:
            self.sr16(op - 0xB8, self.rw())
            self._base = 4

        # --- MOV r/m, reg (88-89) ---
        elif op in (0x88, 0x89):
            w = op & 1
            mod, reg, rm = self.modrm()
            v = self.gr16(reg) if w else self.gr8(reg)
            if mod == 3:
                self.write_rm(rm, False, w, v)
                self._base = 2  # MOV reg, reg
            else:
                addr = self.ea(mod, rm)
                self.write_rm(addr, True, w, v)
                self._base = 9  # MOV mem, reg
                self._add_ea(mod, rm)
                self._add_penalty(addr, w)

        # --- MOV reg, r/m (8A-8B) ---
        elif op in (0x8A, 0x8B):
            w = op & 1
            mod, reg, rm = self.modrm()
            if mod == 3:
                val = self.gr16(rm) if w else self.gr8(rm)
                if w:
                    self.sr16(reg, val)
                else:
                    self.sr8(reg, val)
                self._base = 2  # MOV reg, reg
            else:
                addr = self.ea(mod, rm)
                val = self.rm16(addr) if w else self.rm8(addr)
                if w:
                    self.sr16(reg, val)
                else:
                    self.sr8(reg, val)
                self._base = 8  # MOV reg, mem
                self._add_ea(mod, rm)
                self._add_penalty(addr, w)

        # --- MOV r/m, imm (C6-C7) ---
        elif op in (0xC6, 0xC7):
            w = op & 1
            mod, _, rm = self.modrm()
            if mod == 3:
                imm = self.rw() if w else self.rb()
                self.write_rm(rm, False, w, imm)
                self._base = 4  # MOV reg, imm
            else:
                addr = self.ea(mod, rm)
                imm = self.rw() if w else self.rb()
                self.write_rm(addr, True, w, imm)
                self._base = 10  # MOV mem, imm
                self._add_ea(mod, rm)
                self._add_penalty(addr, w)

        # --- ALU r/m <-> reg (00-3B, low 3 bits 0-3) ---
        elif op < 0x40 and (op & 7) < 4:
            alu_op = (op >> 3) & 7
            d = (op >> 1) & 1
            w = op & 1
            mod, reg, rm = self.modrm()
            if mod == 3:
                # reg, reg
                rm_val = self.gr16(rm) if w else self.gr8(rm)
                reg_val = self.gr16(reg) if w else self.gr8(reg)
                if d:
                    res = self.alu(alu_op, reg_val, rm_val, w)
                    if alu_op != 7:
                        if w:
                            self.sr16(reg, res)
                        else:
                            self.sr8(reg, res)
                else:
                    res = self.alu(alu_op, rm_val, reg_val, w)
                    if alu_op != 7:
                        self.write_rm(rm, False, w, res)
                self._base = 3  # ALU reg, reg
            else:
                addr = self.ea(mod, rm)
                rm_val = self.rm16(addr) if w else self.rm8(addr)
                reg_val = self.gr16(reg) if w else self.gr8(reg)
                self._add_ea(mod, rm)
                self._add_penalty(addr, w)
                if d:
                    # ALU reg, mem
                    res = self.alu(alu_op, reg_val, rm_val, w)
                    if alu_op != 7:
                        if w:
                            self.sr16(reg, res)
                        else:
                            self.sr8(reg, res)
                    self._base = 9  # ALU reg, mem
                else:
                    # ALU mem, reg
                    res = self.alu(alu_op, rm_val, reg_val, w)
                    if alu_op != 7:
                        self.wm16(addr, res) if w else self.wm8(addr, res)
                    self._base = 16  # ALU mem, reg

        # --- ALU AL/AX, imm (04,05,...,3C,3D) ---
        elif op < 0x40 and (op & 7) in (4, 5):
            alu_op = (op >> 3) & 7
            w = op & 1
            imm = self.rw() if w else self.rb()
            if w:
                a = self.regs["ax"]
                res = self.alu(alu_op, a, imm, True)
                if alu_op != 7:
                    self.regs["ax"] = res & 0xFFFF
            else:
                a = self.regs["ax"] & 0xFF
                res = self.alu(alu_op, a, imm, False)
                if alu_op != 7:
                    self.regs["ax"] = (self.regs["ax"] & 0xFF00) | (res & 0xFF)
            self._base = 4  # ALU acc, imm

        # --- INC reg16 (40-47) ---
        elif 0x40 <= op <= 0x47:
            i = op - 0x40
            v = self.gr16(i)
            cf = self.flags["CF"]
            self.uflags(v + 1, v, 1, True, False)
            self.flags["CF"] = cf
            self.sr16(i, (v + 1) & 0xFFFF)
            self._base = 2  # INC reg16 (short)

        # --- DEC reg16 (48-4F) ---
        elif 0x48 <= op <= 0x4F:
            i = op - 0x48
            v = self.gr16(i)
            cf = self.flags["CF"]
            self.uflags(v - 1, v, 1, True, True)
            self.flags["CF"] = cf
            self.sr16(i, (v - 1) & 0xFFFF)
            self._base = 2  # DEC reg16 (short)

        # --- PUSH reg16 (50-57) ---
        elif 0x50 <= op <= 0x57:
            v = self.gr16(op - 0x50)
            self.regs["sp"] = (self.regs["sp"] - 2) & 0xFFFF
            sp = self.regs["sp"]
            self.wm16(sp, v)
            self._base = 11
            self._add_penalty(sp, True)

        # --- POP reg16 (58-5F) ---
        elif 0x58 <= op <= 0x5F:
            sp = self.regs["sp"]
            v = self.rm16(sp)
            self.regs["sp"] = (self.regs["sp"] + 2) & 0xFFFF
            self.sr16(op - 0x58, v)
            self._base = 8
            self._add_penalty(sp, True)

        # --- Conditional jumps (70-7F) ---
        elif 0x70 <= op <= 0x7F:
            off = self.rb()
            if off > 127:
                off -= 256
            taken = self.cond(op & 0xF)
            if taken:
                self.ip = (self.ip + off) & 0xFFFF
                self._base = 16
            else:
                self._base = 4

        # --- Immediate ALU group (80-83) ---
        elif 0x80 <= op <= 0x83:
            w = op & 1
            mod, alu_op, rm = self.modrm()
            if mod == 3:
                dst = self.gr16(rm) if w else self.gr8(rm)
                if op == 0x83:
                    imm = self.rb()
                    if imm > 127:
                        imm -= 256
                    imm &= 0xFFFF
                elif w:
                    imm = self.rw()
                else:
                    imm = self.rb()
                res = self.alu(alu_op, dst, imm, w)
                if alu_op != 7:
                    self.write_rm(rm, False, w, res)
                self._base = 4  # ALU reg, imm
            else:
                addr = self.ea(mod, rm)
                dst = self.rm16(addr) if w else self.rm8(addr)
                if op == 0x83:
                    imm = self.rb()
                    if imm > 127:
                        imm -= 256
                    imm &= 0xFFFF
                elif w:
                    imm = self.rw()
                else:
                    imm = self.rb()
                res = self.alu(alu_op, dst, imm, w)
                if alu_op != 7:
                    self.wm16(addr, res) if w else self.wm8(addr, res)
                self._base = 17  # ALU mem, imm
                self._add_ea(mod, rm)
                self._add_penalty(addr, w)

        # --- TEST r/m, reg (84-85) ---
        elif op in (0x84, 0x85):
            w = op & 1
            mod, reg, rm = self.modrm()
            if mod == 3:
                rm_val = self.gr16(rm) if w else self.gr8(rm)
                reg_val = self.gr16(reg) if w else self.gr8(reg)
                r = rm_val & reg_val
                sb = 0x8000 if w else 0x80
                self.flags["CF"] = self.flags["OF"] = False
                self.flags["ZF"] = (r & (0xFFFF if w else 0xFF)) == 0
                self.flags["SF"] = bool(r & sb)
                self.flags["PF"] = bin(r & 0xFF).count("1") % 2 == 0
                self._base = 3  # TEST reg, reg
            else:
                addr = self.ea(mod, rm)
                rm_val = self.rm16(addr) if w else self.rm8(addr)
                reg_val = self.gr16(reg) if w else self.gr8(reg)
                r = rm_val & reg_val
                sb = 0x8000 if w else 0x80
                self.flags["CF"] = self.flags["OF"] = False
                self.flags["ZF"] = (r & (0xFFFF if w else 0xFF)) == 0
                self.flags["SF"] = bool(r & sb)
                self.flags["PF"] = bin(r & 0xFF).count("1") % 2 == 0
                self._base = 11  # TEST mem, reg
                self._add_ea(mod, rm)
                self._add_penalty(addr, w)

        # --- XCHG r/m, reg (86-87) ---
        elif op in (0x86, 0x87):
            w = op & 1
            mod, reg, rm = self.modrm()
            if mod == 3:
                rm_val = self.gr16(rm) if w else self.gr8(rm)
                reg_val = self.gr16(reg) if w else self.gr8(reg)
                self.write_rm(rm, False, w, reg_val)
                if w:
                    self.sr16(reg, rm_val)
                else:
                    self.sr8(reg, rm_val)
                self._base = 4  # XCHG reg, reg
            else:
                addr = self.ea(mod, rm)
                rm_val = self.rm16(addr) if w else self.rm8(addr)
                reg_val = self.gr16(reg) if w else self.gr8(reg)
                self.write_rm(addr, True, w, reg_val)
                if w:
                    self.sr16(reg, rm_val)
                else:
                    self.sr8(reg, rm_val)
                self._base = 17  # XCHG reg, mem
                self._add_ea(mod, rm)
                self._add_penalty(addr, w)

        # --- NOP / XCHG AX, reg (90-97) ---
        elif 0x90 <= op <= 0x97:
            if op == 0x90:
                self._base = 3  # NOP
            else:
                i = op - 0x90
                a, b = self.regs["ax"], self.gr16(i)
                self.regs["ax"] = b
                self.sr16(i, a)
                self._base = 3  # XCHG AX, reg16 (short)

        # --- MOV mem <-> acc (A0-A3) ---
        elif op in (0xA0, 0xA1, 0xA2, 0xA3):
            w = op & 1
            addr = self.rw()
            if op <= 0xA1:  # MOV acc, mem
                if w:
                    self.regs["ax"] = self.rm16(addr)
                else:
                    self.regs["ax"] = (self.regs["ax"] & 0xFF00) | self.rm8(addr)
            else:  # MOV mem, acc
                if w:
                    self.wm16(addr, self.regs["ax"])
                else:
                    self.wm8(addr, self.regs["ax"] & 0xFF)
            self._base = 10  # acc, direct (EA included)
            self._add_penalty(addr, w)

        # --- Shift/rotate by 1 (D0-D1) ---
        elif op in (0xD0, 0xD1):
            w = op & 1
            mod, sop, rm = self.modrm()
            if mod == 3:
                val = self.gr16(rm) if w else self.gr8(rm)
                mask = 0xFFFF if w else 0xFF
                sb = 0x8000 if w else 0x80
                r = self._do_shift1(sop, val, mask, sb, w)
                self.write_rm(rm, False, w, r)
                self._base = 2  # shift reg, 1
            else:
                addr = self.ea(mod, rm)
                val = self.rm16(addr) if w else self.rm8(addr)
                mask = 0xFFFF if w else 0xFF
                sb = 0x8000 if w else 0x80
                r = self._do_shift1(sop, val, mask, sb, w)
                self.write_rm(addr, True, w, r)
                self._base = 15  # shift mem, 1
                self._add_ea(mod, rm)
                self._add_penalty(addr, w)

        # --- Shift/rotate by CL (D2-D3) ---
        elif op in (0xD2, 0xD3):
            w = op & 1
            mod, sop, rm = self.modrm()
            count = self.regs["cx"] & 0xFF
            if mod == 3:
                val = self.gr16(rm) if w else self.gr8(rm)
                mask = 0xFFFF if w else 0xFF
                sb = 0x8000 if w else 0x80
                r = self._do_shift_cl(sop, val, count, mask, sb, w)
                self.write_rm(rm, False, w, r)
                self._base = 8 + 4 * count  # shift reg, CL
            else:
                addr = self.ea(mod, rm)
                val = self.rm16(addr) if w else self.rm8(addr)
                mask = 0xFFFF if w else 0xFF
                sb = 0x8000 if w else 0x80
                r = self._do_shift_cl(sop, val, count, mask, sb, w)
                self.write_rm(addr, True, w, r)
                self._base = 20 + 4 * count  # shift mem, CL
                self._add_ea(mod, rm)
                self._add_penalty(addr, w)

        # --- CALL near (E8) ---
        elif op == 0xE8:
            off = self.rw()
            if off > 32767:
                off -= 65536
            self.regs["sp"] = (self.regs["sp"] - 2) & 0xFFFF
            sp = self.regs["sp"]
            self.wm16(sp, self.ip)
            self.ip = (self.ip + off) & 0xFFFF
            self._base = 19
            self._add_penalty(sp, True)

        # --- JMP near (E9) ---
        elif op == 0xE9:
            off = self.rw()
            if off > 32767:
                off -= 65536
            self.ip = (self.ip + off) & 0xFFFF
            self._base = 15

        # --- JMP short (EB) ---
        elif op == 0xEB:
            off = self.rb()
            if off > 127:
                off -= 256
            self.ip = (self.ip + off) & 0xFFFF
            self._base = 15

        # --- LOOPNZ (E0), LOOPZ (E1), LOOP (E2), JCXZ (E3) ---
        elif op == 0xE0:
            off = self.rb()
            if off > 127:
                off -= 256
            self.regs["cx"] = (self.regs["cx"] - 1) & 0xFFFF
            if self.regs["cx"] != 0 and not self.flags["ZF"]:
                self.ip = (self.ip + off) & 0xFFFF
                self._base = 18  # LOOPNZ taken
            else:
                self._base = 6  # LOOPNZ not taken
        elif op == 0xE1:
            off = self.rb()
            if off > 127:
                off -= 256
            self.regs["cx"] = (self.regs["cx"] - 1) & 0xFFFF
            if self.regs["cx"] != 0 and self.flags["ZF"]:
                self.ip = (self.ip + off) & 0xFFFF
                self._base = 18  # LOOPZ taken
            else:
                self._base = 6  # LOOPZ not taken
        elif op == 0xE2:
            off = self.rb()
            if off > 127:
                off -= 256
            self.regs["cx"] = (self.regs["cx"] - 1) & 0xFFFF
            if self.regs["cx"] != 0:
                self.ip = (self.ip + off) & 0xFFFF
                self._base = 17  # LOOP taken
            else:
                self._base = 5  # LOOP not taken
        elif op == 0xE3:
            off = self.rb()
            if off > 127:
                off -= 256
            if self.regs["cx"] == 0:
                self.ip = (self.ip + off) & 0xFFFF
                self._base = 18  # JCXZ taken
            else:
                self._base = 6  # JCXZ not taken

        # --- RET near (C3) ---
        elif op == 0xC3:
            sp = self.regs["sp"]
            self.ip = self.rm16(sp)
            self.regs["sp"] = (self.regs["sp"] + 2) & 0xFFFF
            self._base = 8
            self._add_penalty(sp, True)

        # --- F6/F7: TEST/NOT/NEG/MUL/DIV (unary group) ---
        elif op in (0xF6, 0xF7):
            w = op & 1
            mod, sop, rm = self.modrm()
            if mod == 3:
                val = self.gr16(rm) if w else self.gr8(rm)
                loc, is_mem = rm, False
            else:
                addr = self.ea(mod, rm)
                val = self.rm16(addr) if w else self.rm8(addr)
                loc, is_mem = addr, True
                self._add_ea(mod, rm)
                self._add_penalty(addr, w)
            mask = 0xFFFF if w else 0xFF
            sb = 0x8000 if w else 0x80
            if sop == 0:  # TEST r/m, imm
                imm = self.rw() if w else self.rb()
                r = val & imm
                self.flags["CF"] = self.flags["OF"] = False
                self.flags["ZF"] = (r & mask) == 0
                self.flags["SF"] = bool(r & sb)
                self.flags["PF"] = bin(r & 0xFF).count("1") % 2 == 0
                if is_mem:
                    self._base = 11  # TEST mem, imm
                else:
                    self._base = 5  # TEST reg, imm
            elif sop == 2:  # NOT
                self.write_rm(loc, is_mem, w, (~val) & mask)
                if is_mem:
                    self._base = 16  # NOT mem
                else:
                    self._base = 3  # NOT reg
            elif sop == 3:  # NEG
                r = (0 - val) & mask
                self.uflags(0 - val, 0, val, w, True)
                self.flags["CF"] = val != 0
                self.write_rm(loc, is_mem, w, r)
                if is_mem:
                    self._base = 16  # NEG mem
                else:
                    self._base = 3  # NEG reg
            elif sop == 4:  # MUL
                if w:
                    result = self.regs["ax"] * val
                    self.regs["ax"] = result & 0xFFFF
                    self.regs["dx"] = (result >> 16) & 0xFFFF
                    self.flags["CF"] = self.flags["OF"] = self.regs["dx"] != 0
                    if is_mem:
                        self._base = 124  # MUL mem16 (use min)
                    else:
                        self._base = 118  # MUL reg16
                else:
                    result = (self.regs["ax"] & 0xFF) * val
                    self.regs["ax"] = result & 0xFFFF
                    self.flags["CF"] = self.flags["OF"] = (result >> 8) != 0
                    if is_mem:
                        self._base = 76  # MUL mem8
                    else:
                        self._base = 70  # MUL reg8
            elif sop == 5:  # IMUL
                if w:
                    a = self.regs["ax"]
                    if a > 32767:
                        a -= 65536
                    b = val
                    if b > 32767:
                        b -= 65536
                    result = a * b
                    self.regs["ax"] = result & 0xFFFF
                    self.regs["dx"] = (result >> 16) & 0xFFFF
                    sign_ext = (result >> 15) & 0x1FFFF
                    self.flags["CF"] = self.flags["OF"] = sign_ext not in (0, 0x1FFFF)
                    if is_mem:
                        self._base = 134
                    else:
                        self._base = 128
                else:
                    a = self.regs["ax"] & 0xFF
                    if a > 127:
                        a -= 256
                    b = val
                    if b > 127:
                        b -= 256
                    result = a * b
                    self.regs["ax"] = result & 0xFFFF
                    sign_ext = (result >> 7) & 0x1FF
                    self.flags["CF"] = self.flags["OF"] = sign_ext not in (0, 0x1FF)
                    if is_mem:
                        self._base = 86
                    else:
                        self._base = 80
            elif sop == 6:  # DIV
                if w:
                    dividend = (self.regs["dx"] << 16) | self.regs["ax"]
                    if val == 0:
                        raise ValueError("Division by zero")
                    self.regs["ax"] = (dividend // val) & 0xFFFF
                    self.regs["dx"] = (dividend % val) & 0xFFFF
                    if is_mem:
                        self._base = 150
                    else:
                        self._base = 144
                else:
                    dividend = self.regs["ax"]
                    if val == 0:
                        raise ValueError("Division by zero")
                    self.regs["ax"] = (self.regs["ax"] & 0xFF00) | ((dividend // val) & 0xFF)
                    self.sr8(4, dividend % val)
                    if is_mem:
                        self._base = 86
                    else:
                        self._base = 80
            elif sop == 7:  # IDIV
                if w:
                    dividend = (self.regs["dx"] << 16) | self.regs["ax"]
                    if dividend > 0x7FFFFFFF:
                        dividend -= 0x100000000
                    sv = val
                    if sv > 32767:
                        sv -= 65536
                    if sv == 0:
                        raise ValueError("Division by zero")
                    q = int(dividend / sv)
                    r = dividend - q * sv
                    self.regs["ax"] = q & 0xFFFF
                    self.regs["dx"] = r & 0xFFFF
                    if is_mem:
                        self._base = 171
                    else:
                        self._base = 165
                else:
                    dividend = self.regs["ax"]
                    if dividend > 32767:
                        dividend -= 65536
                    sv = val
                    if sv > 127:
                        sv -= 256
                    if sv == 0:
                        raise ValueError("Division by zero")
                    q = int(dividend / sv)
                    r = dividend - q * sv
                    self.regs["ax"] = (self.regs["ax"] & 0xFF00) | (q & 0xFF)
                    self.sr8(4, r & 0xFF)
                    if is_mem:
                        self._base = 107
                    else:
                        self._base = 101
            else:
                raise ValueError(f"Unimplemented F6/F7 sub-op {sop}")

        # --- INC/DEC/CALL/JMP/PUSH r/m (FE-FF) ---
        elif op in (0xFE, 0xFF):
            w = op & 1
            mod, sop, rm = self.modrm()
            if mod == 3:
                val = self.gr16(rm) if w else self.gr8(rm)
                loc, is_mem = rm, False
            else:
                addr = self.ea(mod, rm)
                val = self.rm16(addr) if w else self.rm8(addr)
                loc, is_mem = addr, True
                self._add_ea(mod, rm)
                self._add_penalty(addr, w)
            mask = 0xFFFF if w else 0xFF
            if sop == 0:  # INC
                cf = self.flags["CF"]
                self.uflags(val + 1, val, 1, w, False)
                self.flags["CF"] = cf
                self.write_rm(loc, is_mem, w, (val + 1) & mask)
                if is_mem:
                    self._base = 15  # INC mem
                else:
                    self._base = 3  # INC reg (via FE/FF)
            elif sop == 1:  # DEC
                cf = self.flags["CF"]
                self.uflags(val - 1, val, 1, w, True)
                self.flags["CF"] = cf
                self.write_rm(loc, is_mem, w, (val - 1) & mask)
                if is_mem:
                    self._base = 15  # DEC mem
                else:
                    self._base = 3  # DEC reg (via FE/FF)
            elif sop == 2 and w:  # CALL near indirect
                self.regs["sp"] = (self.regs["sp"] - 2) & 0xFFFF
                sp = self.regs["sp"]
                self.wm16(sp, self.ip)
                self.ip = val & 0xFFFF
                if is_mem:
                    self._base = 21  # CALL indirect mem (approx)
                else:
                    self._base = 16  # CALL indirect reg
                self._add_penalty(sp, True)
            elif sop == 4 and w:  # JMP near indirect
                self.ip = val & 0xFFFF
                if is_mem:
                    self._base = 18  # JMP indirect mem
                else:
                    self._base = 11  # JMP indirect reg
            elif sop == 6 and w:  # PUSH r/m16
                self.regs["sp"] = (self.regs["sp"] - 2) & 0xFFFF
                sp = self.regs["sp"]
                self.wm16(sp, val)
                if is_mem:
                    self._base = 16  # PUSH mem
                else:
                    self._base = 11  # PUSH reg (via FF /6)
                self._add_penalty(sp, True)
            else:
                raise ValueError(f"Unimplemented FE/FF sub-op {sop} w={w}")

        # --- HLT (F4) ---
        elif op == 0xF4:
            self.ip = self.prog_end
            self._base = 2

        # --- Segment override prefixes (skip) ---
        elif op in (0x26, 0x2E, 0x36, 0x3E):
            self._base = 2

        # --- CLC/STC/CMC ---
        elif op == 0xF8:
            self.flags["CF"] = False
            self._base = 2
        elif op == 0xF9:
            self.flags["CF"] = True
            self._base = 2
        elif op == 0xF5:
            self.flags["CF"] = not self.flags["CF"]
            self._base = 2

        # --- LEA (8D) ---
        elif op == 0x8D:
            mod, reg, rm = self.modrm()
            addr = self.ea(mod, rm)
            self.sr16(reg, addr)
            self._base = 2
            self._add_ea(mod, rm)

        else:
            raise ValueError(f"Unknown opcode 0x{op:02X} at IP={self.ip - 1}")

        total = self._base + self._ea + self._pen
        self.total_cycles += total
        self.cycle_log.append((ip_before, self._base, self._ea, self._pen, total))

    # ── shift helpers ──

    def _do_shift1(self, sop, val, mask, sb, w):
        if sop == 4:  # SHL
            r = (val << 1) & mask
            self.flags["CF"] = bool(val & sb)
            self.flags["OF"] = bool((r ^ val) & sb)
        elif sop == 5:  # SHR
            r = val >> 1
            self.flags["CF"] = bool(val & 1)
            self.flags["OF"] = bool(val & sb)
        elif sop == 7:  # SAR
            r = val >> 1
            if val & sb:
                r |= sb
            self.flags["CF"] = bool(val & 1)
            self.flags["OF"] = False
        elif sop == 0:  # ROL
            msb = (val >> (15 if w else 7)) & 1
            r = ((val << 1) | msb) & mask
            self.flags["CF"] = bool(msb)
            self.flags["OF"] = bool((r ^ val) & sb)
        elif sop == 1:  # ROR
            lsb = val & 1
            r = (val >> 1) | (lsb * sb)
            self.flags["CF"] = bool(lsb)
            self.flags["OF"] = bool(r & sb) != bool((r << 1) & sb)
        elif sop == 2:  # RCL
            msb = (val >> (15 if w else 7)) & 1
            r = ((val << 1) | (1 if self.flags["CF"] else 0)) & mask
            self.flags["CF"] = bool(msb)
            self.flags["OF"] = bool((r ^ val) & sb)
        elif sop == 3:  # RCR
            lsb = val & 1
            r = (val >> 1) | (sb if self.flags["CF"] else 0)
            self.flags["CF"] = bool(lsb)
            self.flags["OF"] = bool(r & sb) != bool((r << 1) & sb)
        else:
            raise ValueError(f"Unknown shift op {sop}")
        self.flags["ZF"] = r == 0
        self.flags["SF"] = bool(r & sb)
        self.flags["PF"] = bin(r & 0xFF).count("1") % 2 == 0
        return r

    def _do_shift_cl(self, sop, val, count, mask, sb, w):
        r = val
        for _ in range(count):
            if sop == 4:  # SHL
                self.flags["CF"] = bool(r & sb)
                r = (r << 1) & mask
            elif sop == 5:  # SHR
                self.flags["CF"] = bool(r & 1)
                r >>= 1
            elif sop == 7:  # SAR
                self.flags["CF"] = bool(r & 1)
                msb = r & sb
                r = (r >> 1) | msb
            elif sop == 0:  # ROL
                msb = (r >> (15 if w else 7)) & 1
                r = ((r << 1) | msb) & mask
                self.flags["CF"] = bool(msb)
            elif sop == 1:  # ROR
                lsb = r & 1
                r = (r >> 1) | (lsb * sb)
                self.flags["CF"] = bool(lsb)
        if count > 0:
            self.flags["ZF"] = r == 0
            self.flags["SF"] = bool(r & sb)
            self.flags["PF"] = bin(r & 0xFF).count("1") % 2 == 0
        return r

    def run(self, data):
        self.prog_end = len(data)
        self.mem[: len(data)] = data
        while self.ip < self.prog_end:
            self.step()

    def dump_state(self):
        for r in ("ax", "bx", "cx", "dx", "sp", "bp", "si", "di"):
            print(f"{r}:{self.regs[r]}")
        print(f"ip:{self.ip}")
        fs = " ".join(f for f in ("CF", "PF", "AF", "ZF", "SF", "OF") if self.flags[f])
        print(f"flags:{fs}")
        print(f"cycles:{self.total_cycles}")

    def dump_cycles(self):
        for ip_off, base, ea, pen, tot in self.cycle_log:
            print(f"{ip_off},{base},{ea},{pen},{tot}")
        print(f"TOTAL:{self.total_cycles}")


def main():
    p = argparse.ArgumentParser(description="Intel 8086 CPU Simulator")
    p.add_argument("binary", help="Binary machine code file")
    p.add_argument(
        "--memdump",
        nargs=3,
        metavar=("FILE", "START", "SIZE"),
        help="Dump memory region to file",
    )
    p.add_argument("--cycles", action="store_true", help="Per-instruction cycle breakdown")
    args = p.parse_args()

    with open(args.binary, "rb") as f:
        data = f.read()

    cpu = CPU()
    cpu.run(data)

    if args.cycles:
        cpu.dump_cycles()
    else:
        cpu.dump_state()

    if args.memdump:
        fn, start, size = args.memdump[0], int(args.memdump[1]), int(args.memdump[2])
        with open(fn, "wb") as f:
            f.write(bytes(cpu.mem[start : start + size]))


if __name__ == "__main__":
    main()
