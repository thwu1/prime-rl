#!/usr/bin/env python3
"""Generate three candidate bytecode programs for the custom VM.

Each implements a different cipher variant on a 16-byte block.
Only candidate alpha matches the encrypted output.

Alpha:  8-round generalized Feistel, F(x,k) = ROL(x,7)^ROL(x,13)^SHR(x,3)^k,
        perm (W0,W1,W2,W3) -> (W1,W2,W3,W0^F(W1,K)), key mask 0xA5A5A5A5.
Beta:   8-round generalized Feistel, F(x,k) = ROL(x,5)^ROL(x,11)^SHR(x,5)^k,
        same perm as alpha, key mask 0xC3C3C3C3.
Gamma:  8-round generalized Feistel, same F as alpha, same key mask,
        DIFFERENT perm: (W0,W1,W2,W3) -> (W2,W3,W0^F(W1,K),W1).
"""

import struct
import os


class Assembler:
    def __init__(self):
        self.code = bytearray()

    def emit_load_imm(self, reg, val):
        self.code.append(0x10)
        self.code.append(reg & 7)
        self.code.extend(struct.pack('<I', val & 0xFFFFFFFF))

    def emit_mov(self, dst, src):
        self.code.extend([0x11, dst & 7, src & 7])

    def emit_add(self, dst, a, b):
        self.code.extend([0x20, dst & 7, a & 7, b & 7])

    def emit_xor(self, dst, a, b):
        self.code.extend([0x30, dst & 7, a & 7, b & 7])

    def emit_shl(self, dst, src, n):
        self.code.extend([0x34, dst & 7, src & 7, n & 0x1f])

    def emit_shr(self, dst, src, n):
        self.code.extend([0x35, dst & 7, src & 7, n & 0x1f])

    def emit_rol(self, dst, src, n):
        self.code.extend([0x36, dst & 7, src & 7, n & 0x1f])

    def emit_load_dword(self, dst, addr_reg):
        self.code.extend([0x40, dst & 7, addr_reg & 7])

    def emit_store_dword(self, val_reg, addr_reg):
        self.code.extend([0x41, val_reg & 7, addr_reg & 7])

    def emit_cmp(self, a, b):
        self.code.extend([0x50, a & 7, b & 7])

    def emit_je(self):
        pos = len(self.code)
        self.code.extend([0x51, 0x00, 0x00])
        return pos

    def emit_jne(self):
        pos = len(self.code)
        self.code.extend([0x52, 0x00, 0x00])
        return pos

    def emit_jmp(self):
        pos = len(self.code)
        self.code.extend([0x53, 0x00, 0x00])
        return pos

    def emit_call(self):
        pos = len(self.code)
        self.code.extend([0x60, 0x00, 0x00])
        return pos

    def emit_ret(self):
        self.code.append(0x61)

    def emit_push(self, reg):
        self.code.extend([0x70, reg & 7])

    def emit_pop(self, reg):
        self.code.extend([0x71, reg & 7])

    def emit_syscall(self, n):
        self.code.extend([0xF0, n])

    def emit_nop(self):
        self.code.append(0xFF)

    def patch(self, pos, target):
        struct.pack_into('<H', self.code, pos + 1, target)

    def pos(self):
        return len(self.code)

    def get_bytes(self):
        return bytes(self.code)


# Round keys: first 8 words of fractional part of pi
ROUND_KEYS = [
    0x243F6A88, 0x85A308D3, 0x13198A2E, 0x03707344,
    0xA4093822, 0x299F31D0, 0x082EFA98, 0xEC4E6C89,
]


def _emit_read_input(asm):
    asm.emit_load_imm(0, 0x000)
    asm.emit_load_imm(1, 16)
    asm.emit_syscall(1)


def _emit_store_keys(asm, xor_mask):
    for i, key in enumerate(ROUND_KEYS):
        asm.emit_load_imm(4, key ^ xor_mask)
        asm.emit_load_imm(5, 0x100 + i * 4)
        asm.emit_store_dword(4, 5)


def _emit_load_words(asm):
    asm.emit_load_imm(7, 0x000); asm.emit_load_dword(0, 7)
    asm.emit_load_imm(7, 0x004); asm.emit_load_dword(1, 7)
    asm.emit_load_imm(7, 0x008); asm.emit_load_dword(2, 7)
    asm.emit_load_imm(7, 0x00C); asm.emit_load_dword(3, 7)


def _emit_key_load_in_loop(asm, xor_mask):
    """Load round key K[r4] into r6 (unmasked)."""
    asm.emit_shl(6, 4, 2)
    asm.emit_load_imm(7, 0x100)
    asm.emit_add(6, 6, 7)
    asm.emit_load_dword(6, 6)
    asm.emit_load_imm(7, xor_mask)
    asm.emit_xor(6, 6, 7)


def _emit_output_and_halt(asm):
    asm.emit_load_imm(7, 0x000); asm.emit_store_dword(0, 7)
    asm.emit_load_imm(7, 0x004); asm.emit_store_dword(1, 7)
    asm.emit_load_imm(7, 0x008); asm.emit_store_dword(2, 7)
    asm.emit_load_imm(7, 0x00C); asm.emit_store_dword(3, 7)
    asm.emit_load_imm(0, 0x000)
    asm.emit_load_imm(1, 16)
    asm.emit_syscall(2)
    asm.emit_syscall(3)


def gen_alpha():
    """Cipher alpha: the correct cipher."""
    asm = Assembler()
    XOR_MASK = 0xA5A5A5A5

    _emit_read_input(asm)
    _emit_store_keys(asm, XOR_MASK)
    _emit_load_words(asm)

    # Dead-code branch: if W0 == 0 (never true for ASCII input)
    asm.emit_load_imm(6, 0)
    asm.emit_cmp(0, 6)
    dead_branch = asm.emit_je()

    # Feistel loop: 8 rounds
    asm.emit_load_imm(4, 0)
    asm.emit_load_imm(5, 8)
    loop_start = asm.pos()

    asm.emit_push(4); asm.emit_push(5)
    asm.emit_push(0); asm.emit_push(1); asm.emit_push(2); asm.emit_push(3)

    _emit_key_load_in_loop(asm, XOR_MASK)
    round_call = asm.emit_call()

    asm.emit_pop(3); asm.emit_pop(2); asm.emit_pop(1); asm.emit_pop(0)

    # Permutation: (W0,W1,W2,W3) -> (W1,W2,W3,W0^F(W1,K))
    asm.emit_xor(0, 0, 7)
    asm.emit_mov(6, 0)
    asm.emit_mov(0, 1)
    asm.emit_mov(1, 2)
    asm.emit_mov(2, 3)
    asm.emit_mov(3, 6)

    asm.emit_pop(5); asm.emit_pop(4)
    asm.emit_load_imm(6, 1)
    asm.emit_add(4, 4, 6)
    asm.emit_cmp(4, 5)
    loop_back = asm.emit_jne()
    asm.patch(loop_back, loop_start)

    _emit_output_and_halt(asm)

    # Round function subroutine: F(x,k) = ROL(x,7) ^ ROL(x,13) ^ SHR(x,3) ^ k
    # Input: r1=x, r6=k. Output: r7=F(x,k).
    rf_addr = asm.pos()
    asm.patch(round_call, rf_addr)
    asm.emit_rol(4, 1, 7)
    asm.emit_rol(5, 1, 13)
    asm.emit_xor(4, 4, 5)
    asm.emit_shr(5, 1, 3)
    asm.emit_xor(4, 4, 5)
    asm.emit_xor(7, 4, 6)
    asm.emit_ret()

    # Dead code: simple XOR cipher (decoy, never reached)
    dead_addr = asm.pos()
    asm.patch(dead_branch, dead_addr)
    asm.emit_load_imm(6, 0xDEADBEEF)
    asm.emit_xor(0, 0, 6); asm.emit_xor(1, 1, 6)
    asm.emit_xor(2, 2, 6); asm.emit_xor(3, 3, 6)
    _emit_output_and_halt(asm)

    for _ in range(16):
        asm.emit_nop()

    return asm.get_bytes()


def gen_beta():
    """Cipher beta: different round function and key mask."""
    asm = Assembler()
    XOR_MASK = 0xC3C3C3C3

    _emit_read_input(asm)
    _emit_store_keys(asm, XOR_MASK)
    _emit_load_words(asm)

    # NOP padding (no dead code branch in beta)
    for _ in range(4):
        asm.emit_nop()

    # Feistel loop: 8 rounds
    asm.emit_load_imm(4, 0)
    asm.emit_load_imm(5, 8)
    loop_start = asm.pos()

    asm.emit_push(4); asm.emit_push(5)
    asm.emit_push(0); asm.emit_push(1); asm.emit_push(2); asm.emit_push(3)

    _emit_key_load_in_loop(asm, XOR_MASK)
    round_call = asm.emit_call()

    asm.emit_pop(3); asm.emit_pop(2); asm.emit_pop(1); asm.emit_pop(0)

    # Same permutation as alpha: (W0,W1,W2,W3) -> (W1,W2,W3,W0^F(W1,K))
    asm.emit_xor(0, 0, 7)
    asm.emit_mov(6, 0)
    asm.emit_mov(0, 1)
    asm.emit_mov(1, 2)
    asm.emit_mov(2, 3)
    asm.emit_mov(3, 6)

    asm.emit_pop(5); asm.emit_pop(4)
    asm.emit_load_imm(6, 1)
    asm.emit_add(4, 4, 6)
    asm.emit_cmp(4, 5)
    loop_back = asm.emit_jne()
    asm.patch(loop_back, loop_start)

    _emit_output_and_halt(asm)

    # Round function: F(x,k) = ROL(x,5) ^ ROL(x,11) ^ SHR(x,5) ^ k
    rf_addr = asm.pos()
    asm.patch(round_call, rf_addr)
    asm.emit_rol(4, 1, 5)      # different: ROL 5
    asm.emit_rol(5, 1, 11)     # different: ROL 11
    asm.emit_xor(4, 4, 5)
    asm.emit_shr(5, 1, 5)      # different: SHR 5
    asm.emit_xor(4, 4, 5)
    asm.emit_xor(7, 4, 6)
    asm.emit_ret()

    for _ in range(8):
        asm.emit_nop()

    return asm.get_bytes()


def gen_gamma():
    """Cipher gamma: same round function and keys as alpha, different permutation."""
    asm = Assembler()
    XOR_MASK = 0xA5A5A5A5

    _emit_read_input(asm)
    _emit_store_keys(asm, XOR_MASK)
    _emit_load_words(asm)

    # Decoy: if W0 == W2, jump to NOP sled (never true for typical input)
    asm.emit_cmp(0, 2)
    decoy_branch = asm.emit_je()

    # Feistel loop: 8 rounds
    asm.emit_load_imm(4, 0)
    asm.emit_load_imm(5, 8)
    loop_start = asm.pos()

    asm.emit_push(4); asm.emit_push(5)
    asm.emit_push(0); asm.emit_push(1); asm.emit_push(2); asm.emit_push(3)

    _emit_key_load_in_loop(asm, XOR_MASK)
    round_call = asm.emit_call()

    asm.emit_pop(3); asm.emit_pop(2); asm.emit_pop(1); asm.emit_pop(0)

    # DIFFERENT permutation: (W0,W1,W2,W3) -> (W2,W3,W0^F(W1,K),W1)
    asm.emit_xor(0, 0, 7)      # r0 = W0 ^ F
    # State: r0=W0^F, r1=W1, r2=W2, r3=W3
    asm.emit_mov(6, 1)          # temp = W1
    asm.emit_mov(1, 3)          # r1 = W3
    asm.emit_mov(3, 6)          # r3 = W1
    asm.emit_mov(6, 0)          # temp = W0^F
    asm.emit_mov(0, 2)          # r0 = W2
    asm.emit_mov(2, 6)          # r2 = W0^F
    # Result: r0=W2, r1=W3, r2=W0^F, r3=W1

    asm.emit_pop(5); asm.emit_pop(4)
    asm.emit_load_imm(6, 1)
    asm.emit_add(4, 4, 6)
    asm.emit_cmp(4, 5)
    loop_back = asm.emit_jne()
    asm.patch(loop_back, loop_start)

    _emit_output_and_halt(asm)

    # Round function: same as alpha
    rf_addr = asm.pos()
    asm.patch(round_call, rf_addr)
    asm.emit_rol(4, 1, 7)
    asm.emit_rol(5, 1, 13)
    asm.emit_xor(4, 4, 5)
    asm.emit_shr(5, 1, 3)
    asm.emit_xor(4, 4, 5)
    asm.emit_xor(7, 4, 6)
    asm.emit_ret()

    # Decoy NOP sled target
    decoy_addr = asm.pos()
    asm.patch(decoy_branch, decoy_addr)
    for _ in range(12):
        asm.emit_nop()
    asm.emit_syscall(3)

    for _ in range(8):
        asm.emit_nop()

    return asm.get_bytes()


os.makedirs('/app/candidates', exist_ok=True)

alpha = gen_alpha()
beta = gen_beta()
gamma = gen_gamma()

with open('/app/candidates/alpha.bin', 'wb') as f:
    f.write(alpha)
with open('/app/candidates/beta.bin', 'wb') as f:
    f.write(beta)
with open('/app/candidates/gamma.bin', 'wb') as f:
    f.write(gamma)

print(f"Generated: alpha.bin ({len(alpha)} bytes), "
      f"beta.bin ({len(beta)} bytes), "
      f"gamma.bin ({len(gamma)} bytes)")
