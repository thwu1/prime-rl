#!/usr/bin/env python3
"""Intel 8086 binary decoder, execution simulator, and cycle estimator.

Two modes:
  decode <binary> — disassemble to NASM-compatible assembly (round-trips via nasm -f bin)
  exec <binary>   — simulate execution and output final machine state + total clocks as JSON
"""

import sys
import json

REG16 = ["ax", "cx", "dx", "bx", "sp", "bp", "si", "di"]
REG8 = ["al", "cl", "dl", "bl", "ah", "ch", "dh", "bh"]
EA_BASE = ["bx+si", "bx+di", "bp+si", "bp+di", "si", "di", "bp", "bx"]
GRP1_MN = ["add", "or", "adc", "sbb", "and", "sub", "xor", "cmp"]
ALU_MN = {0: "add", 5: "sub", 7: "cmp"}
JCC_MN = {
    0x70: "jo", 0x71: "jno", 0x72: "jb", 0x73: "jnb",
    0x74: "jz", 0x75: "jnz", 0x76: "jbe", 0x77: "ja",
    0x78: "js", 0x79: "jns", 0x7A: "jp", 0x7B: "jnp",
    0x7C: "jl", 0x7D: "jnl", 0x7E: "jle", 0x7F: "jg",
}


# ============================================================================
# DECODER — produces NASM-compatible assembly that round-trips through nasm
# ============================================================================

def _ea_str(data, ip, mod, rm):
    if mod == 0 and rm == 6:
        d = data[ip] | (data[ip + 1] << 8)
        return f"0x{d:x}", ip + 2
    base = EA_BASE[rm]
    if mod == 0:
        return base, ip
    if mod == 1:
        d = data[ip]
        ip += 1
        d = d - 256 if d >= 128 else d
    else:
        d = data[ip] | (data[ip + 1] << 8)
        ip += 2
        d = d - 0x10000 if d >= 0x8000 else d
    if d == 0:
        return base, ip
    if d > 0:
        return f"{base}+{d}", ip
    return f"{base}{d}", ip


def _parse_modrm(data, ip, w):
    b = data[ip]
    ip += 1
    mod = (b >> 6) & 3
    reg = (b >> 3) & 7
    rm = b & 7
    if mod == 3:
        return reg, (REG16 if w else REG8)[rm], ip, False
    ea, ip = _ea_str(data, ip, mod, rm)
    return reg, f"[{ea}]", ip, True


def _u8(data, ip):
    return data[ip], ip + 1


def _u16(data, ip):
    return data[ip] | (data[ip + 1] << 8), ip + 2


def _s8(data, ip):
    v = data[ip]
    return (v - 256 if v >= 128 else v), ip + 1


def decode(data):
    n = len(data)
    ip = 0
    insts = []
    jump_targets = set()

    while ip < n:
        start = ip
        op = data[ip]
        ip += 1
        asm = None
        target = None

        if 0xB8 <= op <= 0xBF:
            v, ip = _u16(data, ip)
            asm = f"mov {REG16[op - 0xB8]}, {v}"

        elif 0xB0 <= op <= 0xB7:
            v, ip = _u8(data, ip)
            asm = f"mov {REG8[op - 0xB0]}, {v}"

        elif 0x88 <= op <= 0x8B:
            w = op & 1
            d = (op >> 1) & 1
            regs = REG16 if w else REG8
            ri, rm_s, ip, _ = _parse_modrm(data, ip, w)
            if d:
                asm = f"mov {regs[ri]}, {rm_s}"
            else:
                asm = f"mov {rm_s}, {regs[ri]}"

        elif op in (0xA0, 0xA1):
            a, ip = _u16(data, ip)
            asm = f"mov {'ax' if op & 1 else 'al'}, [0x{a:x}]"

        elif op in (0xA2, 0xA3):
            a, ip = _u16(data, ip)
            asm = f"mov [0x{a:x}], {'ax' if op & 1 else 'al'}"

        elif op in (0xC6, 0xC7):
            w = op & 1
            _, rm_s, ip, is_mem = _parse_modrm(data, ip, w)
            if w:
                v, ip = _u16(data, ip)
                sz = "word " if is_mem else ""
            else:
                v, ip = _u8(data, ip)
                sz = "byte " if is_mem else ""
            asm = f"mov {sz}{rm_s}, {v}"

        elif 0x40 <= op <= 0x47:
            asm = f"inc {REG16[op - 0x40]}"

        elif 0x48 <= op <= 0x4F:
            asm = f"dec {REG16[op - 0x48]}"

        elif op in (0x80, 0x81, 0x83):
            w = 0 if op == 0x80 else 1
            ri, rm_s, ip, is_mem = _parse_modrm(data, ip, w)
            if op == 0x80:
                v, ip = _u8(data, ip)
            elif op == 0x81:
                v, ip = _u16(data, ip)
            else:
                v, ip = _s8(data, ip)
            sz = ""
            if is_mem:
                sz = "word " if w else "byte "
            asm = f"{GRP1_MN[ri]} {sz}{rm_s}, {v}"

        elif op in (0x04, 0x05, 0x2C, 0x2D, 0x3C, 0x3D):
            w = op & 1
            g = op >> 3
            mn = ALU_MN[g]
            reg = "ax" if w else "al"
            if w:
                v, ip = _u16(data, ip)
            else:
                v, ip = _u8(data, ip)
            asm = f"{mn} {reg}, {v}"

        elif (op & 7) <= 3 and (op >> 3) in ALU_MN:
            mn = ALU_MN[op >> 3]
            w = op & 1
            d = (op >> 1) & 1
            regs = REG16 if w else REG8
            ri, rm_s, ip, _ = _parse_modrm(data, ip, w)
            if d:
                asm = f"{mn} {regs[ri]}, {rm_s}"
            else:
                asm = f"{mn} {rm_s}, {regs[ri]}"

        elif 0x70 <= op <= 0x7F:
            off, ip = _s8(data, ip)
            target = ip + off
            asm = f"{JCC_MN[op]} L_{target}"
            jump_targets.add(target)

        elif op == 0xE2:
            off, ip = _s8(data, ip)
            target = ip + off
            asm = f"loop L_{target}"
            jump_targets.add(target)

        else:
            raise ValueError(f"Unknown opcode 0x{op:02x} at offset {start}")

        insts.append((start, asm))

    lines = ["bits 16"]
    for off, text in insts:
        if off in jump_targets:
            lines.append(f"L_{off}:")
        lines.append(text)
    return "\n".join(lines) + "\n"


# ============================================================================
# SIMULATOR — executes 8086 machine code, tracks cycles, reports final state
# ============================================================================

# EA calculation clocks from Intel 8086 Family User's Manual
# rm 0-3 are base+index combos, 4-7 are single register
# BX+SI (rm=0), BP+DI (rm=3) = 7 no-disp / 11 with-disp
# BX+DI (rm=1), BP+SI (rm=2) = 8 no-disp / 12 with-disp
# Single reg (rm=4..7) = 5 no-disp / 9 with-disp
# Direct (mod=0,rm=6) = 6
_EA_CLOCKS_NO_DISP = [7, 8, 8, 7, 5, 5, 5, 5]
_EA_CLOCKS_DISP = [11, 12, 12, 11, 9, 9, 9, 9]


def _ea_cost(mod, rm):
    if mod == 3:
        return 0
    if mod == 0 and rm == 6:
        return 6
    if mod == 0:
        return _EA_CLOCKS_NO_DISP[rm]
    return _EA_CLOCKS_DISP[rm]


class Sim8086:
    def __init__(self):
        self.mem = bytearray(1 << 20)
        self.reg = [0] * 8
        self.ip = 0
        self.end = 0
        self.clocks = 0
        self.flags = {"CF": False, "ZF": False, "SF": False,
                      "OF": False, "PF": False, "AF": False}

    def load(self, data):
        self.mem[:len(data)] = data
        self.end = len(data)

    def gr16(self, i):
        return self.reg[i]

    def sr16(self, i, v):
        self.reg[i] = v & 0xFFFF

    def gr8(self, i):
        return self.reg[i] & 0xFF if i < 4 else (self.reg[i - 4] >> 8) & 0xFF

    def sr8(self, i, v):
        v &= 0xFF
        if i < 4:
            self.reg[i] = (self.reg[i] & 0xFF00) | v
        else:
            self.reg[i - 4] = (self.reg[i - 4] & 0x00FF) | (v << 8)

    def mr8(self, a):
        return self.mem[a & 0xFFFFF]

    def mw8(self, a, v):
        self.mem[a & 0xFFFFF] = v & 0xFF

    def mr16(self, a):
        a &= 0xFFFFF
        return self.mem[a] | (self.mem[a + 1] << 8)

    def mw16(self, a, v):
        a &= 0xFFFFF
        self.mem[a] = v & 0xFF
        self.mem[a + 1] = (v >> 8) & 0xFF

    def fetch8(self):
        b = self.mem[self.ip]
        self.ip += 1
        return b

    def fetch16(self):
        v = self.mem[self.ip] | (self.mem[self.ip + 1] << 8)
        self.ip += 2
        return v

    def fetchs8(self):
        b = self.fetch8()
        return b - 256 if b >= 128 else b

    def _rmbase(self, rm):
        tbl = [
            (self.reg[3] + self.reg[6]) & 0xFFFF,
            (self.reg[3] + self.reg[7]) & 0xFFFF,
            (self.reg[5] + self.reg[6]) & 0xFFFF,
            (self.reg[5] + self.reg[7]) & 0xFFFF,
            self.reg[6],
            self.reg[7],
            self.reg[5],
            self.reg[3],
        ]
        return tbl[rm] & 0xFFFF

    def calc_ea(self, mod, rm):
        if mod == 0 and rm == 6:
            return self.fetch16()
        base = self._rmbase(rm)
        if mod == 1:
            return (base + self.fetchs8()) & 0xFFFF
        if mod == 2:
            d = self.fetch16()
            return (base + (d if d < 0x8000 else d - 0x10000)) & 0xFFFF
        return base

    def decode_modrm(self):
        b = self.fetch8()
        mod = (b >> 6) & 3
        reg = (b >> 3) & 7
        rm = b & 7
        if mod == 3:
            return reg, (True, rm), mod, rm
        return reg, (False, self.calc_ea(mod, rm)), mod, rm

    def read_op(self, op, w):
        if op[0]:
            return self.gr8(op[1]) if w == 8 else self.gr16(op[1])
        return self.mr8(op[1]) if w == 8 else self.mr16(op[1])

    def write_op(self, op, v, w):
        if op[0]:
            (self.sr8 if w == 8 else self.sr16)(op[1], v)
        else:
            (self.mw8 if w == 8 else self.mw16)(op[1], v)

    @staticmethod
    def _parity(v):
        return bin(v & 0xFF).count("1") % 2 == 0

    def fl_add(self, a, b, w):
        mask = (1 << w) - 1
        full = a + b
        r = full & mask
        msb = 1 << (w - 1)
        self.flags["CF"] = full > mask
        self.flags["ZF"] = r == 0
        self.flags["SF"] = bool(r & msb)
        self.flags["PF"] = self._parity(r)
        sa, sb, sr = bool(a & msb), bool(b & msb), bool(r & msb)
        self.flags["OF"] = (sa == sb) and (sr != sa)
        self.flags["AF"] = ((a & 0xF) + (b & 0xF)) > 0xF
        return r

    def fl_sub(self, a, b, w):
        mask = (1 << w) - 1
        r = (a - b) & mask
        msb = 1 << (w - 1)
        self.flags["CF"] = a < b
        self.flags["ZF"] = r == 0
        self.flags["SF"] = bool(r & msb)
        self.flags["PF"] = self._parity(r)
        sa, sb, sr = bool(a & msb), bool(b & msb), bool(r & msb)
        self.flags["OF"] = (sa != sb) and (sr != sa)
        self.flags["AF"] = (a & 0xF) < (b & 0xF)
        return r

    def step(self):
        op = self.fetch8()

        # MOV r16, imm16 (B8+r) — 4 clocks
        if 0xB8 <= op <= 0xBF:
            self.sr16(op - 0xB8, self.fetch16())
            self.clocks += 4
            return

        # MOV r8, imm8 (B0+r) — 4 clocks
        if 0xB0 <= op <= 0xB7:
            self.sr8(op - 0xB0, self.fetch8())
            self.clocks += 4
            return

        # MOV r/m <-> reg (88-8B)
        if 0x88 <= op <= 0x8B:
            w = 16 if (op & 1) else 8
            d = (op >> 1) & 1
            ri, rm, mod, rmf = self.decode_modrm()
            ea = _ea_cost(mod, rmf)
            if d == 0:
                v = self.gr8(ri) if w == 8 else self.gr16(ri)
                self.write_op(rm, v, w)
                if mod == 3:
                    self.clocks += 2  # reg, reg
                else:
                    self.clocks += 9 + ea  # mem, reg
            else:
                v = self.read_op(rm, w)
                (self.sr8 if w == 8 else self.sr16)(ri, v)
                if mod == 3:
                    self.clocks += 2  # reg, reg
                else:
                    self.clocks += 8 + ea  # reg, mem
            return

        # MOV AL/AX <-> [moffs16] (A0-A3) — 10 clocks
        if op in (0xA0, 0xA1, 0xA2, 0xA3):
            addr = self.fetch16()
            if op == 0xA0:
                self.sr8(0, self.mr8(addr))
            elif op == 0xA1:
                self.reg[0] = self.mr16(addr)
            elif op == 0xA2:
                self.mw8(addr, self.gr8(0))
            else:
                self.mw16(addr, self.reg[0])
            self.clocks += 10
            return

        # MOV r/m, imm (C6/C7)
        if op in (0xC6, 0xC7):
            w = 16 if (op & 1) else 8
            _, rm, mod, rmf = self.decode_modrm()
            imm = self.fetch16() if w == 16 else self.fetch8()
            self.write_op(rm, imm, w)
            if mod == 3:
                self.clocks += 4  # reg, imm
            else:
                self.clocks += 10 + _ea_cost(mod, rmf)  # mem, imm
            return

        # ADD/SUB/CMP r/m <-> reg (00-03, 28-2B, 38-3B)
        grp = op >> 3
        sub_bits = op & 7
        if sub_bits <= 3 and grp in (0, 5, 7):
            w = 16 if (sub_bits & 1) else 8
            d = (sub_bits >> 1) & 1
            ri, rm, mod, rmf = self.decode_modrm()
            ea = _ea_cost(mod, rmf)
            if d == 0:
                dst = self.read_op(rm, w)
                src = self.gr8(ri) if w == 8 else self.gr16(ri)
            else:
                dst = self.gr8(ri) if w == 8 else self.gr16(ri)
                src = self.read_op(rm, w)
            r = self.fl_add(dst, src, w) if grp == 0 else self.fl_sub(dst, src, w)
            if grp != 7:
                if d == 0:
                    self.write_op(rm, r, w)
                else:
                    (self.sr8 if w == 8 else self.sr16)(ri, r)
            # Cycle timing
            if mod == 3:
                self.clocks += 3  # reg, reg
            elif grp == 7:
                # CMP: no write-back, always 9+EA regardless of direction
                self.clocks += 9 + ea
            elif d == 0:
                # mem, reg (destination is memory, read-modify-write)
                self.clocks += 16 + ea
            else:
                # reg, mem (destination is register)
                self.clocks += 9 + ea
            return

        # ADD/SUB/CMP AL/AX, imm (04/05, 2C/2D, 3C/3D) — 4 clocks
        if op in (0x04, 0x05, 0x2C, 0x2D, 0x3C, 0x3D):
            w = 16 if (op & 1) else 8
            imm = self.fetch16() if w == 16 else self.fetch8()
            g = op >> 3
            dst = self.reg[0] if w == 16 else self.gr8(0)
            r = self.fl_add(dst, imm, w) if g == 0 else self.fl_sub(dst, imm, w)
            if g != 7:
                if w == 16:
                    self.reg[0] = r
                else:
                    self.sr8(0, r)
            self.clocks += 4
            return

        # Group 1: arith r/m, imm (80/81/83)
        if op in (0x80, 0x81, 0x83):
            ri, rm, mod, rmf = self.decode_modrm()
            ea = _ea_cost(mod, rmf)
            if op == 0x80:
                w, imm = 8, self.fetch8()
            elif op == 0x81:
                w, imm = 16, self.fetch16()
            else:
                w = 16
                imm = self.fetchs8() & 0xFFFF
            dst = self.read_op(rm, w)
            if ri == 0:  # ADD
                r = self.fl_add(dst, imm, w)
                self.write_op(rm, r, w)
            elif ri == 5:  # SUB
                r = self.fl_sub(dst, imm, w)
                self.write_op(rm, r, w)
            elif ri == 7:  # CMP
                self.fl_sub(dst, imm, w)
            elif ri == 1:  # OR
                r = (dst | imm) & ((1 << w) - 1)
                self.flags["CF"] = self.flags["OF"] = False
                self.flags["ZF"] = r == 0
                self.flags["SF"] = bool(r & (1 << (w - 1)))
                self.flags["PF"] = self._parity(r)
                self.write_op(rm, r, w)
            elif ri == 4:  # AND
                r = (dst & imm) & ((1 << w) - 1)
                self.flags["CF"] = self.flags["OF"] = False
                self.flags["ZF"] = r == 0
                self.flags["SF"] = bool(r & (1 << (w - 1)))
                self.flags["PF"] = self._parity(r)
                self.write_op(rm, r, w)
            else:
                raise ValueError(f"Unimplemented group1 /{ri}")
            # Cycle timing
            if mod == 3:
                self.clocks += 4  # reg, imm
            elif ri == 7:
                self.clocks += 10 + ea  # CMP mem, imm (read-only)
            else:
                self.clocks += 17 + ea  # ADD/SUB/OR/AND mem, imm (read-modify-write)
            return

        # Conditional jumps (70-7F)
        if 0x70 <= op <= 0x7F:
            off = self.fetchs8()
            f = self.flags
            conds = {
                0x70: f["OF"],
                0x71: not f["OF"],
                0x72: f["CF"],
                0x73: not f["CF"],
                0x74: f["ZF"],
                0x75: not f["ZF"],
                0x76: f["CF"] or f["ZF"],
                0x77: not f["CF"] and not f["ZF"],
                0x78: f["SF"],
                0x79: not f["SF"],
                0x7A: f["PF"],
                0x7B: not f["PF"],
                0x7C: f["SF"] != f["OF"],
                0x7D: f["SF"] == f["OF"],
                0x7E: f["ZF"] or (f["SF"] != f["OF"]),
                0x7F: not f["ZF"] and (f["SF"] == f["OF"]),
            }
            taken = conds[op]
            if taken:
                self.ip = (self.ip + off) & 0xFFFF
                self.clocks += 16
            else:
                self.clocks += 4
            return

        # LOOP (E2)
        if op == 0xE2:
            off = self.fetchs8()
            self.reg[1] = (self.reg[1] - 1) & 0xFFFF
            if self.reg[1] != 0:
                self.ip = (self.ip + off) & 0xFFFF
                self.clocks += 17
            else:
                self.clocks += 5
            return

        # INC r16 (40+r) — 2 clocks
        if 0x40 <= op <= 0x47:
            i = op - 0x40
            v = self.gr16(i)
            cf = self.flags["CF"]
            self.fl_add(v, 1, 16)
            self.flags["CF"] = cf
            self.sr16(i, (v + 1) & 0xFFFF)
            self.clocks += 2
            return

        # DEC r16 (48+r) — 2 clocks
        if 0x48 <= op <= 0x4F:
            i = op - 0x48
            v = self.gr16(i)
            cf = self.flags["CF"]
            self.fl_sub(v, 1, 16)
            self.flags["CF"] = cf
            self.sr16(i, (v - 1) & 0xFFFF)
            self.clocks += 2
            return

        raise ValueError(f"Unknown opcode 0x{op:02X} at IP=0x{self.ip - 1:04X}")

    def run(self):
        for _ in range(10_000_000):
            if self.ip >= self.end:
                break
            self.step()

    def state(self):
        s = {name: self.reg[i] for i, name in enumerate(REG16)}
        s["ip"] = self.ip
        for flag in ("CF", "ZF", "SF", "OF", "PF"):
            s[flag] = self.flags[flag]
        s["total_clocks"] = self.clocks
        return s


# ============================================================================
# MAIN
# ============================================================================

def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <decode|exec> <binary_file>", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]
    with open(sys.argv[2], "rb") as f:
        data = f.read()

    if mode == "decode":
        print(decode(data), end="")
    elif mode == "exec":
        sim = Sim8086()
        sim.load(data)
        sim.run()
        print(json.dumps(sim.state()))
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
