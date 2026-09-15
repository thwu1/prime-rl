#!/usr/bin/env python3

"""
VM Bytecode Compiler with Obfuscation.

Produces obfuscated StackVM-27 bytecode implementing the key validation
algorithm recovered from reverse-engineering vm_runner and reference.bc.
The output satisfies:
  - Functional correctness for arbitrary inputs
  - Shannon entropy >= 4.5 bits/byte
  - Instruction count >= 500
  - Dead code ratio >= 15%
  - Opaque predicates >= 5
"""

import struct
import random

random.seed(42)

# ===== Algorithm constants (recovered from reference.bc RE) =====
MAGIC  = [0xA5B4C3D2, 0x1F2E3D4C, 0x9A8B7C6D, 0x5E4F3A2B, 0xD1C2B3A4]
PRIMES = [0x01000193, 0x811C9DC5, 0xC4CEB9FE, 0x13375EED, 0xDEADC0DE]
ROUND2 = [0x85EBCA6B, 0xC2B2AE35, 0x7FEB352D, 0x846CA68B, 0x9E3779B9]

# ===== Opcodes (recovered from vm_runner binary RE) =====
OP_NOP    = 0x00; OP_PUSH32 = 0x01; OP_PUSH8  = 0x02
OP_LOAD   = 0x03; OP_STORE  = 0x04; OP_DUP    = 0x05
OP_DROP   = 0x06; OP_SWAP   = 0x07; OP_ADD    = 0x08
OP_SUB    = 0x09; OP_MUL    = 0x0A; OP_XOR    = 0x0B
OP_AND    = 0x0C; OP_OR     = 0x0D; OP_SHR    = 0x0E
OP_SHL    = 0x0F; OP_ROTR   = 0x10; OP_ROTL   = 0x11
OP_MOD    = 0x12; OP_CMP_EQ = 0x13; OP_CMP_NE = 0x14
OP_JMP    = 0x15; OP_JZ     = 0x16; OP_JNZ    = 0x17
OP_HALT   = 0x18; OP_NOT    = 0x19; OP_OVER   = 0x1A


class Assembler:
    """Bytecode assembler with label resolution."""

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


# ===== Obfuscation primitives =====

def emit_dead_block(a):
    """Emit a varied block of unreachable instructions ending with HALT."""
    pat = random.randint(0, 6)
    if pat == 0:
        a.push32(random.randint(0, 0xFFFFFFFF))
        a.push32(random.randint(0, 0xFFFFFFFF))
        a.add(); a.push8(random.randint(1, 31)); a.shl()
        a.not_(); a.drop(); a.halt(1)
    elif pat == 1:
        a.load(random.randint(8, 15))
        a.push32(random.randint(0, 0xFFFFFFFF))
        a.xor(); a.push8(random.randint(1, 31)); a.rotr()
        a.store(random.randint(16, 23))
        a.push32(random.randint(0, 0xFFFFFFFF)); a.mul(); a.drop()
        a.halt(1)
    elif pat == 2:
        for _ in range(random.randint(3, 5)):
            a.push32(random.randint(0, 0xFFFFFFFF))
        for _ in range(random.randint(2, 4)):
            random.choice([a.add, a.sub, a.mul, a.xor, a.and_, a.or_])()
        a.drop(); a.halt(1)
    elif pat == 3:
        a.push32(random.randint(0, 0xFFFFFFFF))
        a.dup(); a.push8(random.randint(1, 31)); a.shr()
        a.xor(); a.push32(random.randint(0, 0xFFFFFFFF))
        a.mul(); a.store(random.randint(8, 15)); a.halt(1)
    elif pat == 4:
        a.push32(random.randint(0, 0xFFFFFFFF))
        a.push32(random.randint(0, 0xFFFFFFFF))
        a.swap(); a.sub(); a.not_()
        a.push8(random.randint(1, 31)); a.rotl()
        a.push32(random.randint(0, 0xFFFFFFFF))
        a.and_(); a.drop(); a.halt(1)
    elif pat == 5:
        a.push8(random.randint(0, 255))
        a.push8(random.randint(0, 255))
        a.push8(random.randint(1, 31)); a.shl()
        a.or_(); a.push32(random.randint(0, 0xFFFFFFFF))
        a.add(); a.push8(random.randint(1, 31)); a.rotr()
        a.drop(); a.halt(1)
    else:
        a.push32(random.randint(0, 0xFFFFFFFF))
        a.push32(random.randint(0, 0xFFFFFFFF))
        a.over(); a.mul(); a.xor()
        a.push8(random.randint(1, 31)); a.shr()
        a.store(random.randint(16, 23)); a.halt(1)


def emit_opaque_pred(a, label_continue, dead_label):
    """Emit an always-true condition jumping to label_continue, then dead code."""
    pred = random.randint(0, 4)
    if pred == 0:
        v = random.randint(0, 0xFFFFFFFF)
        a.push32(v); a.push32(v); a.cmp_eq(); a.jnz(label_continue)
    elif pred == 1:
        v = random.randint(0, 0xFFFFFFFF)
        a.push32(v); a.push32(v); a.xor(); a.jz(label_continue)
    elif pred == 2:
        v = random.randint(0, 0xFFFFFFFF)
        a.push32(v); a.push32(v); a.sub(); a.jz(label_continue)
    elif pred == 3:
        a.push8(0); a.not_(); a.jnz(label_continue)
    else:
        v = random.randint(1, 0xFFFFFFFF)
        a.push32(v); a.dup(); a.and_(); a.jnz(label_continue)
    emit_dead_block(a)
    a.label(dead_label)


def emit_junk(a):
    """Emit stack-neutral junk instructions."""
    jt = random.randint(0, 8)
    if jt == 0:
        a.push32(random.randint(0, 0xFFFFFFFF)); a.drop()
    elif jt == 1:
        a.push8(random.randint(0, 255)); a.drop()
    elif jt == 2:
        a.nop()
    elif jt == 3:
        a.load(random.randint(10, 15)); a.drop()
    elif jt == 4:
        a.push32(random.randint(0, 0xFFFFFFFF))
        a.push32(random.randint(0, 0xFFFFFFFF))
        a.add(); a.drop()
    elif jt == 5:
        a.push32(random.randint(0, 0xFFFFFFFF))
        a.dup(); a.xor(); a.drop()
    elif jt == 6:
        a.push32(random.randint(0, 0xFFFFFFFF))
        a.not_(); a.drop()
    elif jt == 7:
        a.push8(random.randint(0, 255))
        a.push8(random.randint(0, 255))
        a.swap(); a.drop(); a.drop()
    else:
        a.push32(random.randint(0, 0xFFFFFFFF))
        a.push32(random.randint(0, 0xFFFFFFFF))
        a.xor(); a.drop()


# ===== Main compiler =====

def compile_bytecode():
    a = Assembler()
    dc = [0]  # dead block counter

    def next_dead():
        name = f"_dead_{dc[0]}"
        dc[0] += 1
        return name

    # -- Prologue: opaque predicate --
    emit_opaque_pred(a, "init", next_dead())
    a.label("init")

    # Decoy memory stores for entropy
    for slot in range(8, 16):
        a.push32(random.randint(0, 0xFFFFFFFF))
        a.store(slot)

    # -- Main validation loop (unrolled for 5 groups) --
    for i in range(5):
        magic  = MAGIC[i]
        prime  = PRIMES[i]
        round2 = ROUND2[i]

        # Pre-group opaque predicate
        cont_label = f"g{i}_start"
        emit_opaque_pred(a, cont_label, next_dead())
        a.label(cont_label)

        # Pre-group junk
        for _ in range(random.randint(3, 5)):
            emit_junk(a)

        # ---- Round 1 ----
        a.load(0)                   # seed
        a.push32(magic)
        a.xor()                     # seed ^ MAGIC[i]

        emit_junk(a)

        a.push32(prime)
        a.mul()                     # * PRIMES[i]
        a.push8(13)
        a.rotr()                    # ROTR 13
        a.dup()
        a.push8(16)
        a.shr()
        a.xor()                     # val ^ (val >> 16)

        # Jump over mid-round dead code
        mid_label = f"g{i}_r2"
        a.jmp(mid_label)
        emit_dead_block(a)
        a.label(f"_g{i}_mid_dead")
        a.label(mid_label)

        emit_junk(a)

        # ---- Round 2 ----
        a.push32(round2)
        a.add()                     # val + ROUND2[i]
        a.load(0)                   # seed
        a.xor()                     # ^ seed
        a.push8(7)
        a.rotl()                    # ROTL 7
        a.push32(0x5BD1E995)
        a.mul()                     # * MURMUR
        a.dup()
        a.push8(15)
        a.shr()
        a.xor()                     # val ^ (val >> 15)

        # Store expected value
        a.store(6)

        # Post-round obfuscation: opaque predicate for even groups, jmp+dead for odd
        cmp_label = f"g{i}_cmp"
        if i % 2 == 0:
            emit_opaque_pred(a, cmp_label, next_dead())
        else:
            a.jmp(cmp_label)
            emit_dead_block(a)
            a.label(f"_g{i}_post_dead")

        a.label(cmp_label)

        # ---- Compare ----
        a.load(6)                   # expected
        a.load(i + 1)              # actual key group
        a.cmp_eq()
        a.jz("fail")               # mismatch -> reject

        # ---- Seed update ----
        a.load(0)                   # seed
        a.load(i + 1)              # key group
        a.xor()                     # seed ^ key[i]
        a.push32(magic)
        a.add()                     # + MAGIC[i]
        a.push8(11)
        a.rotr()                    # ROTR 11
        a.push32(0x1B873593)
        a.mul()                     # * FINALIZE
        a.store(0)                  # update seed

        # Post-group junk
        for _ in range(random.randint(2, 4)):
            emit_junk(a)

    # -- Pre-accept opaque predicate --
    emit_opaque_pred(a, "accept", next_dead())

    a.label("accept")
    a.halt(0)

    # -- Trailing dead code blocks for inflation + entropy --
    for k in range(8):
        emit_dead_block(a)
        a.label(f"_trailing_dead_{k}")

    a.label("fail")
    a.halt(1)

    return a.resolve()


if __name__ == "__main__":
    bc = compile_bytecode()
    with open("/app/output.bc", "wb") as f:
        f.write(bc)
    print(f"Compiled {len(bc)} bytes of obfuscated bytecode")
