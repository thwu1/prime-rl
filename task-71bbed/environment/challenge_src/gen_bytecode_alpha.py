#!/usr/bin/env python3
"""Generate encrypted bytecode for the VM crackme alpha variant.

Algorithm: FNV-1a hash -> MurmurHash3 fmix64 finalizer -> custom bit mixing
Includes opaque predicate + dead code path for anti-analysis.
"""
import struct

# Opcodes - must match vm.c
NOP=0x00; PUSH8=0x01; PUSH64=0x02; PUSH_R=0x03; POP_R=0x04
ADD=0x05; SUB=0x06; MUL=0x07; XOR=0x08; AND=0x09; OR=0x0A
SHR=0x0B; SHL=0x0C; MOD=0x0D; NOT=0x0E; CMP_EQ=0x0F; CMP_LT=0x10
JMP=0x11; JZ=0x12; JNZ=0x13; LOAD_INP=0x14; INP_LEN=0x15
DUP=0x16; SWAP=0x17; ROTL=0x18; HALT=0x19; LOAD_KEY=0x1A; ROTR=0x1B

XOR_KEY = [0xA5, 0x3C, 0x7E, 0xF1]

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

    # ========== Phase 1: FNV-1a hash of username ==========
    a.push64(0xcbf29ce484222325)   # FNV offset basis
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

    a.push_r(R3)
    a.load_inp()                    # push username[i]
    a.push_r(R2)
    a.xor()                         # h ^= byte
    a.push64(0x100000001b3)         # FNV prime
    a.mul()                         # h *= prime
    a.pop_r(R2)

    a.push_r(R3)
    a.push8(1)
    a.add()
    a.pop_r(R3)                     # i++
    a.jmp('loop')

    a.label('loop_end')

    # ========== Opaque predicate + dead code ==========
    # 7 * 3 = 21, compare with 22 -> always 0, jnz never taken
    a.push8(7)
    a.push8(3)
    a.mul()
    a.push8(22)
    a.cmp_eq()
    a.jnz('fake')
    a.jmp('phase2')

    a.label('fake')
    # Dead code: fake verification path (never executed)
    a.push_r(R2)
    a.push64(0x12345678AABBCCDD)
    a.xor()
    a.pop_r(R2)
    a.push_r(R2)
    a.push64(0x9988776655443322)
    a.mul()
    a.pop_r(R2)
    a.push_r(R2)
    a.load_key()
    a.cmp_eq()
    a.pop_r(R0)
    a.halt()

    a.label('phase2')

    # ========== Phase 2: MurmurHash3 finalizer ==========
    # h ^= h >> 33
    a.push_r(R2); a.push_r(R2); a.push8(33); a.shr(); a.xor(); a.pop_r(R2)
    # h *= 0xff51afd7ed558ccd
    a.push_r(R2); a.push64(0xff51afd7ed558ccd); a.mul(); a.pop_r(R2)
    # h ^= h >> 33
    a.push_r(R2); a.push_r(R2); a.push8(33); a.shr(); a.xor(); a.pop_r(R2)
    # h *= 0xc4ceb9fe1a85ec53
    a.push_r(R2); a.push64(0xc4ceb9fe1a85ec53); a.mul(); a.pop_r(R2)
    # h ^= h >> 33
    a.push_r(R2); a.push_r(R2); a.push8(33); a.shr(); a.xor(); a.pop_r(R2)

    # ========== Phase 3: Additional bit mixing ==========
    # h ^= golden ratio constant
    a.push_r(R2); a.push64(0x9E3779B97F4A7C15); a.xor(); a.pop_r(R2)
    # h = rotl(h, 17)
    a.push_r(R2); a.push8(17); a.rotl(); a.pop_r(R2)
    # h *= 0x517CC1B727220A95
    a.push_r(R2); a.push64(0x517CC1B727220A95); a.mul(); a.pop_r(R2)
    # h ^= h >> 27
    a.push_r(R2); a.push_r(R2); a.push8(27); a.shr(); a.xor(); a.pop_r(R2)
    # h = rotr(h, 13)
    a.push_r(R2); a.push8(13); a.rotr(); a.pop_r(R2)
    # h += 0xBEEFCAFE12345678
    a.push_r(R2); a.push64(0xBEEFCAFE12345678); a.add(); a.pop_r(R2)
    # h ^= h >> 31
    a.push_r(R2); a.push_r(R2); a.push8(31); a.shr(); a.xor(); a.pop_r(R2)

    # ========== Phase 4: Compare with serial key ==========
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
        h = 0xcbf29ce484222325
        for b in username.encode():
            h ^= b
            h = (h * 0x100000001b3) & MASK
        h ^= h >> 33
        h = (h * 0xff51afd7ed558ccd) & MASK
        h ^= h >> 33
        h = (h * 0xc4ceb9fe1a85ec53) & MASK
        h ^= h >> 33
        h ^= 0x9E3779B97F4A7C15
        h = ((h << 17) | (h >> 47)) & MASK
        h = (h * 0x517CC1B727220A95) & MASK
        h ^= h >> 27
        h = ((h >> 13) | (h << 51)) & MASK
        h = (h + 0xBEEFCAFE12345678) & MASK
        h ^= h >> 31
        return h

    for name in ['admin', 'test', 'hello']:
        s = keygen(name)
        print(f'  {name}: {s:#018x}')
