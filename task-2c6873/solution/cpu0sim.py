#!/usr/bin/env python3
"""
Cpu0 Simulator - loads ELF32 big-endian executables and simulates
the full Cpu0 ISA with HI/LO registers and hardwired $zero.
"""

import sys
import struct

# ELF constants
ELFCLASS32 = 1
ELFDATA2MSB = 2
ET_EXEC = 2
EM_CPU0 = 0xC9
PT_LOAD = 1


def load_elf(path):
    with open(path, "rb") as f:
        data = f.read()
    assert data[0:4] == b"\x7fELF" and data[4] == ELFCLASS32 and data[5] == ELFDATA2MSB

    (e_type, e_machine, _, e_entry, e_phoff, _, _, _,
     e_phentsize, e_phnum, _, _, _) = struct.unpack_from(">HHIIIIIHHHHHH", data, 16)
    assert e_type == ET_EXEC and e_machine == EM_CPU0

    mem = bytearray(65536)
    code_end = 0
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, p_offset, p_vaddr, _, p_filesz, p_memsz, _, _ = \
            struct.unpack_from(">IIIIIIII", data, off)
        if p_type == PT_LOAD:
            mem[p_vaddr:p_vaddr + p_filesz] = data[p_offset:p_offset + p_filesz]
            code_end = max(code_end, p_vaddr + p_memsz)
    return mem, e_entry, code_end


class Cpu0:
    def __init__(self, mem, entry, code_end):
        self.mem = mem
        self.code_end = code_end
        self.r = [0] * 16
        self.r[13] = 0xFF00
        self.r[14] = 0xFFFFFFFF
        self.hi = 0
        self.lo = 0
        self.pc = entry

    def rr(self, n):
        return 0 if n == 0 else self.r[n]

    def wr(self, n, v):
        if n != 0:
            self.r[n] = v & 0xFFFFFFFF

    def r32(self, a):
        return struct.unpack_from(">I", self.mem, (a & 0xFFFFFFFF) % 65536)[0]

    def w32(self, a, v):
        struct.pack_into(">I", self.mem, (a & 0xFFFFFFFF) % 65536, v & 0xFFFFFFFF)

    def r16(self, a):
        return struct.unpack_from(">H", self.mem, (a & 0xFFFFFFFF) % 65536)[0]

    def w16(self, a, v):
        struct.pack_into(">H", self.mem, (a & 0xFFFFFFFF) % 65536, v & 0xFFFF)

    def r8(self, a):
        return self.mem[(a & 0xFFFFFFFF) % 65536]

    def w8(self, a, v):
        self.mem[(a & 0xFFFFFFFF) % 65536] = v & 0xFF

    @staticmethod
    def sext(v, bits):
        return v - (1 << bits) if v & (1 << (bits - 1)) else v

    @staticmethod
    def s32(v):
        v &= 0xFFFFFFFF
        return v - 0x100000000 if v & 0x80000000 else v

    @staticmethod
    def clz32(v):
        if v == 0: return 32
        n = 0
        if not (v & 0xFFFF0000): n += 16; v <<= 16
        if not (v & 0xFF000000): n += 8; v <<= 8
        if not (v & 0xF0000000): n += 4; v <<= 4
        if not (v & 0xC0000000): n += 2; v <<= 2
        if not (v & 0x80000000): n += 1
        return n

    @staticmethod
    def rotl(v, a):
        a &= 31
        return ((v << a) | (v >> (32 - a))) & 0xFFFFFFFF

    @staticmethod
    def rotr(v, a):
        a &= 31
        return ((v >> a) | (v << (32 - a))) & 0xFFFFFFFF

    def run(self):
        count = 0
        while 0 <= self.pc < self.code_end and count < 10_000_000:
            self.step(self.r32(self.pc))
            count += 1

    def step(self, inst):
        op = (inst >> 24) & 0xFF
        ra = (inst >> 20) & 0xF
        rb = (inst >> 16) & 0xF
        rc = (inst >> 12) & 0xF
        cx12 = inst & 0xFFF
        cx16 = inst & 0xFFFF
        cx24 = inst & 0xFFFFFF
        sx16 = self.sext(cx16, 16)
        sx24 = self.sext(cx24, 24)
        npc = self.pc + 4

        if op == 0x00: pass  # NOP
        # Load/Store
        elif op == 0x01: self.wr(ra, self.r32((self.rr(rb) + sx16) & 0xFFFFFFFF))
        elif op == 0x02: self.w32((self.rr(rb) + sx16) & 0xFFFFFFFF, self.rr(ra))
        elif op == 0x03: self.wr(ra, self.sext(self.r8((self.rr(rb)+sx16)&0xFFFFFFFF), 8) & 0xFFFFFFFF)
        elif op == 0x04: self.wr(ra, self.r8((self.rr(rb)+sx16)&0xFFFFFFFF))
        elif op == 0x05: self.w8((self.rr(rb)+sx16)&0xFFFFFFFF, self.rr(ra))
        elif op == 0x06: self.wr(ra, self.sext(self.r16((self.rr(rb)+sx16)&0xFFFFFFFF), 16) & 0xFFFFFFFF)
        elif op == 0x07: self.wr(ra, self.r16((self.rr(rb)+sx16)&0xFFFFFFFF))
        elif op == 0x08: self.w16((self.rr(rb)+sx16)&0xFFFFFFFF, self.rr(ra))
        # Immediate ALU
        elif op == 0x09: self.wr(ra, (self.rr(rb) + sx16) & 0xFFFFFFFF)
        elif op == 0x0C: self.wr(ra, self.rr(rb) & cx16)
        elif op == 0x0D: self.wr(ra, self.rr(rb) | cx16)
        elif op == 0x0E: self.wr(ra, self.rr(rb) ^ cx16)
        elif op == 0x0F: self.wr(ra, (cx16 << 16) & 0xFFFFFFFF)
        # Register ALU
        elif op == 0x11: self.wr(ra, (self.rr(rb) + self.rr(rc)) & 0xFFFFFFFF)
        elif op == 0x12: self.wr(ra, (self.rr(rb) - self.rr(rc)) & 0xFFFFFFFF)
        elif op == 0x13: self.wr(ra, (self.rr(rb) + self.rr(rc)) & 0xFFFFFFFF)
        elif op == 0x14: self.wr(ra, (self.rr(rb) - self.rr(rc)) & 0xFFFFFFFF)
        elif op == 0x15: self.wr(ra, self.clz32(self.rr(rb)))
        elif op == 0x16: self.wr(ra, self.clz32((~self.rr(rb)) & 0xFFFFFFFF))
        elif op == 0x17: self.wr(ra, (self.rr(rb) * self.rr(rc)) & 0xFFFFFFFF)
        elif op == 0x18: self.wr(ra, self.rr(rb) & self.rr(rc))
        elif op == 0x19: self.wr(ra, self.rr(rb) | self.rr(rc))
        elif op == 0x1A: self.wr(ra, self.rr(rb) ^ self.rr(rc))
        elif op == 0x1B: self.wr(ra, (~(self.rr(rb) | self.rr(rc))) & 0xFFFFFFFF)
        # Shift/Rotate immediate
        elif op == 0x1C: self.wr(ra, self.rotl(self.rr(rb), cx12))
        elif op == 0x1D: self.wr(ra, self.rotr(self.rr(rb), cx12))
        elif op == 0x1E: self.wr(ra, (self.rr(rb) << (cx12 & 31)) & 0xFFFFFFFF)
        elif op == 0x1F: self.wr(ra, self.rr(rb) >> (cx12 & 31))
        elif op == 0x20: self.wr(ra, (self.s32(self.rr(rb)) >> (cx12 & 31)) & 0xFFFFFFFF)
        # Shift/Rotate register
        elif op == 0x21: self.wr(ra, (self.s32(self.rr(rb)) >> (self.rr(rc)&31)) & 0xFFFFFFFF)
        elif op == 0x22: self.wr(ra, (self.rr(rb) << (self.rr(rc)&31)) & 0xFFFFFFFF)
        elif op == 0x23: self.wr(ra, self.rr(rb) >> (self.rr(rc)&31))
        elif op == 0x24: self.wr(ra, self.rotl(self.rr(rb), self.rr(rc)))
        elif op == 0x25: self.wr(ra, self.rotr(self.rr(rb), self.rr(rc)))
        # SLT
        elif op == 0x26: self.wr(ra, 1 if self.s32(self.rr(rb)) < sx16 else 0)
        elif op == 0x27: self.wr(ra, 1 if self.rr(rb) < (sx16 & 0xFFFFFFFF) else 0)
        elif op == 0x28: self.wr(ra, 1 if self.s32(self.rr(rb)) < self.s32(self.rr(rc)) else 0)
        elif op == 0x29: self.wr(ra, 1 if self.rr(rb) < self.rr(rc) else 0)
        # CMP
        elif op == 0x2A:
            a, b = self.s32(self.rr(ra)), self.s32(self.rr(rb))
            self.r[15] = (1<<31) if a < b else (1<<30) if a == b else 0
        elif op == 0x2B:
            a, b = self.rr(ra), self.rr(rb)
            self.r[15] = (1<<31) if a < b else (1<<30) if a == b else 0
        # Conditional jumps (SW flags)
        elif op == 0x30:
            if self.r[15] & (1<<30): npc = (self.pc+4+sx24)&0xFFFFFFFF
        elif op == 0x31:
            if not (self.r[15] & (1<<30)): npc = (self.pc+4+sx24)&0xFFFFFFFF
        elif op == 0x32:
            if self.r[15] & (1<<31): npc = (self.pc+4+sx24)&0xFFFFFFFF
        elif op == 0x33:
            sw = self.r[15]
            if not (sw&(1<<31)) and not (sw&(1<<30)): npc = (self.pc+4+sx24)&0xFFFFFFFF
        elif op == 0x34:
            sw = self.r[15]
            if (sw&(1<<31)) or (sw&(1<<30)): npc = (self.pc+4+sx24)&0xFFFFFFFF
        elif op == 0x35:
            if not (self.r[15]&(1<<31)): npc = (self.pc+4+sx24)&0xFFFFFFFF
        # Unconditional jumps
        elif op == 0x36: npc = (self.pc+4+sx24)&0xFFFFFFFF
        elif op == 0x37:
            if self.rr(ra) == self.rr(rb): npc = (self.pc+4+sx16)&0xFFFFFFFF
        elif op == 0x38:
            if self.rr(ra) != self.rr(rb): npc = (self.pc+4+sx16)&0xFFFFFFFF
        elif op == 0x39:
            self.wr(14, self.pc+4); npc = self.rr(rb)
        elif op == 0x3A:
            self.wr(14, self.pc+4); npc = (self.pc+4+sx24)&0xFFFFFFFF
        elif op == 0x3B:
            self.wr(14, self.pc+4); npc = (self.pc+4+sx24)&0xFFFFFFFF
        elif op == 0x3C:
            npc = self.rr(ra)
        # Multiply/Divide
        elif op == 0x41:
            r = self.s32(self.rr(ra)) * self.s32(self.rr(rb))
            self.lo = r & 0xFFFFFFFF; self.hi = (r >> 32) & 0xFFFFFFFF
        elif op == 0x42:
            r = self.rr(ra) * self.rr(rb)
            self.lo = r & 0xFFFFFFFF; self.hi = (r >> 32) & 0xFFFFFFFF
        elif op == 0x43:
            a, b = self.s32(self.rr(ra)), self.s32(self.rr(rb))
            if b != 0:
                q = int(a / b); self.lo = q & 0xFFFFFFFF; self.hi = (a - q*b) & 0xFFFFFFFF
        elif op == 0x44:
            a, b = self.rr(ra), self.rr(rb)
            if b != 0:
                self.lo = (a // b) & 0xFFFFFFFF; self.hi = (a % b) & 0xFFFFFFFF
        # HI/LO
        elif op == 0x46: self.wr(ra, self.hi)
        elif op == 0x47: self.wr(ra, self.lo)
        elif op == 0x48: self.hi = self.rr(ra)
        elif op == 0x49: self.lo = self.rr(ra)

        self.pc = npc

    def dump(self):
        for i in range(16):
            print(f"r{i} = {self.r[i]}")
        print(f"HI = {self.hi}")
        print(f"LO = {self.lo}")


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <executable>", file=sys.stderr)
        sys.exit(1)
    mem, entry, code_end = load_elf(sys.argv[1])
    cpu = Cpu0(mem, entry, code_end)
    cpu.run()
    cpu.dump()


if __name__ == "__main__":
    main()
