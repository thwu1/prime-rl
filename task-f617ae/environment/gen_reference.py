#!/usr/bin/env python3
"""Generate clean (unobfuscated) reference bytecode for the key validation algorithm.
Outputs reference.bc in the current directory."""

import struct

# Algorithm constants
MAGIC  = [0xA5B4C3D2, 0x1F2E3D4C, 0x9A8B7C6D, 0x5E4F3A2B, 0xD1C2B3A4]
PRIMES = [0x01000193, 0x811C9DC5, 0xC4CEB9FE, 0x13375EED, 0xDEADC0DE]
ROUND2 = [0x85EBCA6B, 0xC2B2AE35, 0x7FEB352D, 0x846CA68B, 0x9E3779B9]

# Opcodes
OP_PUSH32 = 0x01
OP_PUSH8  = 0x02
OP_LOAD   = 0x03
OP_STORE  = 0x04
OP_DUP    = 0x05
OP_ADD    = 0x08
OP_MUL    = 0x0A
OP_XOR    = 0x0B
OP_SHR    = 0x0E
OP_ROTR   = 0x10
OP_ROTL   = 0x11
OP_CMP_EQ = 0x13
OP_JZ     = 0x16
OP_HALT   = 0x18


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

    def push32(self, val):
        self._emit(OP_PUSH32); self._emit32(val)

    def push8(self, val):
        self._emit(OP_PUSH8); self._emit(val)

    def load(self, addr):
        self._emit(OP_LOAD); self._emit(addr)

    def store(self, addr):
        self._emit(OP_STORE); self._emit(addr)

    def dup(self):
        self._emit(OP_DUP)

    def add(self):
        self._emit(OP_ADD)

    def mul(self):
        self._emit(OP_MUL)

    def xor(self):
        self._emit(OP_XOR)

    def shr(self):
        self._emit(OP_SHR)

    def rotr(self):
        self._emit(OP_ROTR)

    def rotl(self):
        self._emit(OP_ROTL)

    def cmp_eq(self):
        self._emit(OP_CMP_EQ)

    def jz(self, lbl):
        self._emit(OP_JZ)
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


def generate():
    a = Assembler()

    for i in range(5):
        # Round 1: compute expected value from seed
        a.load(0)                   # push seed
        a.push32(MAGIC[i])
        a.xor()                     # seed ^ MAGIC[i]
        a.push32(PRIMES[i])
        a.mul()                     # * PRIMES[i]
        a.push8(13)
        a.rotr()                    # ROTR(val, 13)
        a.dup()
        a.push8(16)
        a.shr()
        a.xor()                     # val ^ (val >> 16)

        # Round 2: further mix with seed
        a.push32(ROUND2[i])
        a.add()                     # val + ROUND2[i]
        a.load(0)                   # push seed
        a.xor()                     # ^ seed
        a.push8(7)
        a.rotl()                    # ROTL(val, 7)
        a.push32(0x5BD1E995)
        a.mul()                     # * MURMUR
        a.dup()
        a.push8(15)
        a.shr()
        a.xor()                     # val ^ (val >> 15)

        # Compare with key group
        a.load(i + 1)               # key_group[i]
        a.cmp_eq()
        a.jz("fail")                # mismatch -> reject

        # Update seed for next group
        a.load(0)                   # seed
        a.load(i + 1)               # key_group[i]
        a.xor()                     # seed ^ key[i]
        a.push32(MAGIC[i])
        a.add()                     # + MAGIC[i]
        a.push8(11)
        a.rotr()                    # ROTR(seed, 11)
        a.push32(0x1B873593)
        a.mul()                     # * FINALIZE
        a.store(0)                  # update seed

    # All 5 groups passed
    a.halt(0)

    a.label("fail")
    a.halt(1)

    return a.resolve()


if __name__ == "__main__":
    bc = generate()
    with open("reference.bc", "wb") as f:
        f.write(bc)
    print(f"Generated {len(bc)} bytes of reference bytecode")
