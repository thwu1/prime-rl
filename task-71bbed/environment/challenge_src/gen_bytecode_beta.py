#!/usr/bin/env python3
"""Generate encrypted bytecode for the VM crackme beta variant.

Algorithm: DJB2a hash (64-bit) -> xxHash/CRC-inspired mixing
No anti-analysis techniques (intentionally weaker for comparative analysis).
"""
import struct

# Opcodes - must match vm.c
NOP=0x00; PUSH8=0x01; PUSH64=0x02; PUSH_R=0x03; POP_R=0x04
ADD=0x05; SUB=0x06; MUL=0x07; XOR=0x08; AND=0x09; OR=0x0A
SHR=0x0B; SHL=0x0C; MOD=0x0D; NOT=0x0E; CMP_EQ=0x0F; CMP_LT=0x10
JMP=0x11; JZ=0x12; JNZ=0x13; LOAD_INP=0x14; INP_LEN=0x15
DUP=0x16; SWAP=0x17; ROTL=0x18; HALT=0x19; LOAD_KEY=0x1A; ROTR=0x1B

XOR_KEY = [0xD7, 0x4B, 0x92, 0xE3]

R0, R1, R2, R3, R4, R5, R6, R7 = range(8)

class Asm:
    def __init__(self):
        self.buf = bytearray()
        self.labels = {}
        self.fixups = []

    def _b(self, *args):
        for b in args:
            self.buf.append(b & 0xFF)

    def _u16(self, v):
        self.buf.extend(struct.pack('<H', v & 0xFFFF))

    def _u64(self, v):
        self.buf.extend(struct.pack('<Q', v & 0xFFFFFFFFFFFFFFFF))

    def label(self, name):
        self.labels[name] = len(self.buf)

    def push8(self, v):  self._b(PUSH8, v)
    def push64(self, v): self._b(PUSH64); self._u64(v)
    def push_r(self, r): self._b(PUSH_R, r)
    def pop_r(self, r):  self._b(POP_R, r)
    def add(self):       self._b(ADD)
    def sub(self):       self._b(SUB)
    def mul(self):       self._b(MUL)
    def xor(self):       self._b(XOR)
    def and_(self):      self._b(AND)
    def or_(self):       self._b(OR)
    def shr(self):       self._b(SHR)
    def shl(self):       self._b(SHL)
    def mod(self):       self._b(MOD)
    def not_(self):      self._b(NOT)
    def cmp_eq(self):    self._b(CMP_EQ)
    def cmp_lt(self):    self._b(CMP_LT)
    def dup(self):       self._b(DUP)
    def swap(self):      self._b(SWAP)
    def rotl(self):      self._b(ROTL)
    def rotr(self):      self._b(ROTR)
    def halt(self):      self._b(HALT)
    def load_key(self):  self._b(LOAD_KEY)
    def load_inp(self):  self._b(LOAD_INP)
    def inp_len(self):   self._b(INP_LEN)
    def nop(self):       self._b(NOP)

    def jmp(self, lbl):
        self._b(JMP)
        self.fixups.append((len(self.buf), lbl))
        self._u16(0)

    def jz(self, lbl):
        self._b(JZ)
        self.fixups.append((len(self.buf), lbl))
        self._u16(0)

    def jnz(self, lbl):
        self._b(JNZ)
        self.fixups.append((len(self.buf), lbl))
        self._u16(0)

    def build(self):
        for pos, lbl in self.fixups:
            t = self.labels[lbl]
            struct.pack_into('<H', self.buf, pos, t)
        return bytes(self.buf)


def gen():
    a = Asm()

    # ========== Phase 1: DJB2a hash of username ==========
    # h = h * 33 ^ byte (the XOR variant of DJB2)
    # Seed is 64-bit extension: 0x1505 repeated = 0x1505150515051505
    a.push64(0x1505150515051505)   # DJB2 seed (64-bit)
    a.pop_r(R2)                     # R2 = h
    a.push8(0)
    a.pop_r(R3)                     # R3 = i = 0
    a.inp_len()
    a.pop_r(R4)                     # R4 = len(username)

    a.label('loop')
    a.push_r(R3)
    a.push_r(R4)
    a.cmp_lt()                      # i < len?
    a.jz('loop_end')

    # h = ((h << 5) + h) ^ byte = h * 33 ^ byte
    a.push_r(R2)
    a.push8(5)
    a.shl()                         # h << 5
    a.push_r(R2)
    a.add()                         # (h << 5) + h = h * 33
    a.push_r(R3)
    a.load_inp()                    # push username[i]
    a.xor()                         # h * 33 ^ byte
    a.pop_r(R2)

    a.push_r(R3)
    a.push8(1)
    a.add()
    a.pop_r(R3)                     # i++
    a.jmp('loop')

    a.label('loop_end')

    # ========== Phase 2: Mixing (xxHash/CRC-inspired) ==========
    # h ^= CRC-64-ECMA polynomial
    a.push_r(R2); a.push64(0xC96C5795D7870F42); a.xor(); a.pop_r(R2)
    # h = rotl(h, 23)
    a.push_r(R2); a.push8(23); a.rotl(); a.pop_r(R2)
    # h *= xxHash PRIME64_5
    a.push_r(R2); a.push64(0x2545F4914F6CDD1D); a.mul(); a.pop_r(R2)
    # h ^= h >> 29
    a.push_r(R2); a.push_r(R2); a.push8(29); a.shr(); a.xor(); a.pop_r(R2)
    # h = rotr(h, 19)
    a.push_r(R2); a.push8(19); a.rotr(); a.pop_r(R2)
    # h += golden ratio variant addend
    a.push_r(R2); a.push64(0x3C6EF372FE94F82B); a.add(); a.pop_r(R2)
    # h ^= h >> 31
    a.push_r(R2); a.push_r(R2); a.push8(31); a.shr(); a.xor(); a.pop_r(R2)

    # ========== Phase 3: Compare with serial key ==========
    a.push_r(R2)
    a.load_key()
    a.cmp_eq()
    a.pop_r(R0)
    a.halt()

    return a.build()


def encrypt(code):
    return bytes(b ^ XOR_KEY[i % 4] for i, b in enumerate(code))


def to_c_array(data):
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        lines.append('    ' + ', '.join(f'0x{b:02x}' for b in chunk) + ',')
    return '\n'.join(lines)


if __name__ == '__main__':
    code = gen()
    enc = encrypt(code)

    with open('xorkey.h', 'w') as f:
        f.write('static const uint8_t xor_key[4] = {')
        f.write(', '.join(f'0x{b:02x}' for b in XOR_KEY))
        f.write('};\n')

    with open('bytecode.h', 'w') as f:
        f.write(f'/* Auto-generated encrypted bytecode - {len(enc)} bytes */\n')
        f.write(f'static const uint8_t vm_bytecode[{len(enc)}] = {{\n')
        f.write(to_c_array(enc))
        f.write('\n};\n')
    print(f'Generated {len(code)} bytes of bytecode ({len(enc)} encrypted)')

    # Verify algorithm
    def keygen(username):
        MASK = 0xFFFFFFFFFFFFFFFF
        h = 0x1505150515051505
        for b in username.encode():
            h = ((((h << 5) & MASK) + h) & MASK) ^ b
        h ^= 0xC96C5795D7870F42
        h = ((h << 23) | (h >> 41)) & MASK
        h = (h * 0x2545F4914F6CDD1D) & MASK
        h ^= h >> 29
        h = ((h >> 19) | (h << 45)) & MASK
        h = (h + 0x3C6EF372FE94F82B) & MASK
        h ^= h >> 31
        return h

    for name in ['admin', 'test', 'hello']:
        s = keygen(name)
        print(f'  {name}: {s:#018x}')
