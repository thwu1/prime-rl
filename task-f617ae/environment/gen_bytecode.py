#!/usr/bin/env python3
"""Generate encrypted bytecode for the VM license validator.
Outputs a C header file (bytecode.h) to stdout."""

import struct

# ===== Algorithm constants =====
MAGIC  = [0xA5B4C3D2, 0x1F2E3D4C, 0x9A8B7C6D, 0x5E4F3A2B, 0xD1C2B3A4]
PRIMES = [0x01000193, 0x811C9DC5, 0xC4CEB9FE, 0x13375EED, 0xDEADC0DE]
ROUND2 = [0x85EBCA6B, 0xC2B2AE35, 0x7FEB352D, 0x846CA68B, 0x9E3779B9]

# ===== Opcodes =====
OP_NOP    = 0x00
OP_PUSH32 = 0x01
OP_PUSH8  = 0x02
OP_LOAD   = 0x03
OP_STORE  = 0x04
OP_DUP    = 0x05
OP_DROP   = 0x06
OP_SWAP   = 0x07
OP_ADD    = 0x08
OP_SUB    = 0x09
OP_MUL    = 0x0A
OP_XOR    = 0x0B
OP_AND    = 0x0C
OP_OR     = 0x0D
OP_SHR    = 0x0E
OP_SHL    = 0x0F
OP_ROTR   = 0x10
OP_ROTL   = 0x11
OP_MOD    = 0x12
OP_CMP_EQ = 0x13
OP_CMP_NE = 0x14
OP_JMP    = 0x15
OP_JZ     = 0x16
OP_JNZ    = 0x17
OP_HALT   = 0x18
OP_NOT    = 0x19
OP_OVER   = 0x1A


class Assembler:
    def __init__(self):
        self.code = bytearray()
        self.labels = {}
        self.fixups = []

    def pos(self):
        return len(self.code)

    def label(self, name):
        self.labels[name] = self.pos()

    def _emit(self, b):
        self.code.append(b & 0xFF)

    def _emit16(self, v):
        self.code.extend(struct.pack('<H', v & 0xFFFF))

    def _emit32(self, v):
        self.code.extend(struct.pack('<I', v & 0xFFFFFFFF))

    def nop(self):       self._emit(OP_NOP)
    def dup(self):       self._emit(OP_DUP)
    def drop(self):      self._emit(OP_DROP)
    def swap(self):      self._emit(OP_SWAP)
    def add(self):       self._emit(OP_ADD)
    def sub(self):       self._emit(OP_SUB)
    def mul(self):       self._emit(OP_MUL)
    def xor(self):       self._emit(OP_XOR)
    def and_(self):      self._emit(OP_AND)
    def or_(self):       self._emit(OP_OR)
    def shr(self):       self._emit(OP_SHR)
    def shl(self):       self._emit(OP_SHL)
    def rotr(self):      self._emit(OP_ROTR)
    def rotl(self):      self._emit(OP_ROTL)
    def mod(self):       self._emit(OP_MOD)
    def cmp_eq(self):    self._emit(OP_CMP_EQ)
    def cmp_ne(self):    self._emit(OP_CMP_NE)
    def not_(self):      self._emit(OP_NOT)
    def over(self):      self._emit(OP_OVER)

    def push32(self, val):
        self._emit(OP_PUSH32); self._emit32(val)

    def push8(self, val):
        self._emit(OP_PUSH8); self._emit(val)

    def load(self, addr):
        self._emit(OP_LOAD); self._emit(addr)

    def store(self, addr):
        self._emit(OP_STORE); self._emit(addr)

    def jmp(self, lbl):
        self._emit(OP_JMP)
        self.fixups.append((self.pos(), lbl))
        self._emit16(0)

    def jz(self, lbl):
        self._emit(OP_JZ)
        self.fixups.append((self.pos(), lbl))
        self._emit16(0)

    def jnz(self, lbl):
        self._emit(OP_JNZ)
        self.fixups.append((self.pos(), lbl))
        self._emit16(0)

    def halt(self, code):
        self._emit(OP_HALT); self._emit(code)

    def resolve(self):
        for offset, name in self.fixups:
            if name not in self.labels:
                raise ValueError(f"Unresolved label: {name}")
            struct.pack_into('<H', self.code, offset, self.labels[name])
        return bytes(self.code)


def generate_bytecode():
    """Generate the validation bytecode.

    VM memory layout (pre-loaded by C wrapper):
      mem[0]   = seed (hash of username)
      mem[1-5] = key groups (parsed from hex)
      mem[6-7] = temp working storage
      mem[8+]  = unused / decoy
    """
    a = Assembler()

    # ===== Obfuscation preamble =====
    # XOR seed with constant then XOR back (no-op on value)
    a.load(0)
    a.push32(0xCAFEBABE)
    a.xor()
    a.push32(0xCAFEBABE)
    a.xor()
    a.store(0)

    # Jump over dead code block 1
    a.jmp("phase1")

    # Dead code block 1 (never executed)
    a.push32(0xDEADBEEF)
    a.push32(0x12345678)
    a.add()
    a.push8(3)
    a.shl()
    a.drop()
    a.halt(1)
    a.nop()
    a.nop()

    a.label("phase1")

    # Store decoy value in unused memory
    a.push32(0x0BADF00D)
    a.store(8)

    # Opaque predicate: always-true comparison, always jumps
    a.push32(0x12345678)
    a.push32(0x12345678)
    a.cmp_eq()
    a.jnz("real_start")

    # Dead code block 2
    a.halt(1)
    a.push32(0xFFFFFFFF)
    a.halt(1)

    a.label("real_start")

    # ===== Main validation: 5 key groups =====
    for i in range(5):
        magic  = MAGIC[i]
        prime  = PRIMES[i]
        round2 = ROUND2[i]

        # Per-group junk (varies to confuse pattern matching)
        if i == 1:
            a.load(8); a.drop()
        elif i == 2:
            a.push8(42); a.nop(); a.drop()
        elif i == 3:
            a.nop(); a.nop()
        elif i == 4:
            a.push8(1); a.push8(2); a.swap(); a.drop(); a.drop()

        # --- Round 1: compute val from seed ---
        a.load(0)               # push seed
        a.push32(magic)
        a.xor()                 # seed ^ MAGIC[i]
        a.push32(prime)
        a.mul()                 # * PRIMES[i]
        a.push8(13)
        a.rotr()                # rotr 13
        a.dup()
        a.push8(16)
        a.shr()
        a.xor()                 # val ^ (val >> 16)

        # --- Round 2: further mix with seed ---
        a.push32(round2)
        a.add()                 # val + ROUND2[i]
        a.load(0)               # push seed again
        a.xor()                 # ^ seed
        a.push8(7)
        a.rotl()                # rotl 7
        a.push32(0x5BD1E995)
        a.mul()                 # * murmur constant
        a.dup()
        a.push8(15)
        a.shr()
        a.xor()                 # val ^ (val >> 15)

        # Store expected in temp, jump over dead code
        a.store(6)
        a.jmp(f"cmp_g{i}")

        # Inter-section dead code
        a.push32(0xBAAAAAAD)
        a.halt(1)

        a.label(f"cmp_g{i}")

        # --- Compare expected with actual key group ---
        a.load(6)               # expected
        a.load(i + 1)           # actual (key group i)
        a.cmp_eq()
        a.jz("fail")            # if not equal -> fail

        # --- Update seed for next group ---
        a.load(0)               # seed
        a.load(i + 1)           # key group value
        a.xor()                 # seed ^ key[i]
        a.push32(magic)
        a.add()                 # + MAGIC[i]
        a.push8(11)
        a.rotr()                # rotr 11
        a.push32(0x1B873593)
        a.mul()                 # * murmurhash3 constant
        a.store(0)              # update seed

        a.nop()                 # post-group padding

    # All groups passed
    a.halt(0)

    a.label("fail")
    a.halt(1)

    return a.resolve()


def encrypt_bytecode(bytecode):
    """Encrypt bytecode with position-dependent rolling XOR."""
    enc = bytearray()
    for i, b in enumerate(bytecode):
        key = ((i * 0x37) + 0x42) & 0xFF
        enc.append(b ^ key)
    return bytes(enc)


def to_c_array(data, name="g_bytecode"):
    """Format bytes as a C static array."""
    lines = [f"static const unsigned char {name}[] = {{"]
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_vals = ", ".join(f"0x{b:02X}" for b in chunk)
        lines.append(f"    {hex_vals},")
    lines.append("};")
    lines.append(f"static const int {name}_len = sizeof({name});")
    return "\n".join(lines)


if __name__ == "__main__":
    bc = generate_bytecode()
    enc = encrypt_bytecode(bc)
    print("/* Auto-generated - DO NOT EDIT */")
    print(f"/* Plain bytecode: {len(bc)} bytes */")
    print(f"/* Decryption: byte[i] ^= ((i * 0x37) + 0x42) & 0xFF */")
    print()
    print(to_c_array(enc))
