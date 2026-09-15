#!/usr/bin/env python3
"""Generate program.bin - Feistel cipher bytecode for the custom VM.

This assembler creates a bytecode program implementing an 8-round generalized
Feistel network with XOR-masked round keys derived from pi constants, a
round function using rotate and shift operations, and dead code for obfuscation.
"""
import struct
import sys

code = bytearray()


def emit_load_imm(reg, val):
    code.append(0x10)
    code.append(reg & 7)
    code.extend(struct.pack('<I', val & 0xFFFFFFFF))


def emit_mov(dst, src):
    code.extend([0x11, dst & 7, src & 7])


def emit_add(dst, a, b):
    code.extend([0x20, dst & 7, a & 7, b & 7])


def emit_xor(dst, a, b):
    code.extend([0x30, dst & 7, a & 7, b & 7])


def emit_shl(dst, src, n):
    code.extend([0x34, dst & 7, src & 7, n & 0x1f])


def emit_shr(dst, src, n):
    code.extend([0x35, dst & 7, src & 7, n & 0x1f])


def emit_rol(dst, src, n):
    code.extend([0x36, dst & 7, src & 7, n & 0x1f])


def emit_load_dword(dst, addr_reg):
    code.extend([0x40, dst & 7, addr_reg & 7])


def emit_store_dword(val_reg, addr_reg):
    code.extend([0x41, val_reg & 7, addr_reg & 7])


def emit_cmp(a, b):
    code.extend([0x50, a & 7, b & 7])


def emit_jne_placeholder():
    pos = len(code)
    code.extend([0x52, 0x00, 0x00])
    return pos


def emit_je_placeholder():
    pos = len(code)
    code.extend([0x51, 0x00, 0x00])
    return pos


def emit_call_placeholder():
    pos = len(code)
    code.extend([0x60, 0x00, 0x00])
    return pos


def emit_ret():
    code.append(0x61)


def emit_push(reg):
    code.extend([0x70, reg & 7])


def emit_pop(reg):
    code.extend([0x71, reg & 7])


def emit_syscall(n):
    code.extend([0xF0, n])


def emit_nop():
    code.append(0xFF)


def patch_target(pos, target):
    struct.pack_into('<H', code, pos + 1, target)


# Round keys (first 8 words of fractional pi)
ROUND_KEYS = [0x243F6A88, 0x85A308D3, 0x13198A2E, 0x03707344,
              0xA4093822, 0x299F31D0, 0x082EFA98, 0xEC4E6C89]
XOR_MASK = 0xA5A5A5A5

# === MAIN CODE ===

# Step 1: Read 16 bytes of input to memory address 0x000
emit_load_imm(0, 0x000)
emit_load_imm(1, 16)
emit_syscall(1)

# Step 2: Store XOR-masked round keys at memory 0x100
for i, key in enumerate(ROUND_KEYS):
    masked = key ^ XOR_MASK
    emit_load_imm(4, masked)
    emit_load_imm(5, 0x100 + i * 4)
    emit_store_dword(4, 5)

# Step 3: Load W0-W3 from memory
emit_load_imm(7, 0x000)
emit_load_dword(0, 7)
emit_load_imm(7, 0x004)
emit_load_dword(1, 7)
emit_load_imm(7, 0x008)
emit_load_dword(2, 7)
emit_load_imm(7, 0x00C)
emit_load_dword(3, 7)

# Dead code branch (red herring - only taken if W0 == 0)
emit_load_imm(6, 0)
emit_cmp(0, 6)
dead_branch = emit_je_placeholder()

# Feistel loop setup
emit_load_imm(4, 0)   # r4 = round counter
emit_load_imm(5, 8)   # r5 = num rounds

loop_start = len(code)

# Save loop vars and current word state
emit_push(4)
emit_push(5)
emit_push(0)
emit_push(1)
emit_push(2)
emit_push(3)

# Load round key K[i]: addr = 0x100 + r4 * 4
emit_shl(6, 4, 2)
emit_load_imm(7, 0x100)
emit_add(6, 6, 7)
emit_load_dword(6, 6)

# Unmask key: r6 ^= XOR_MASK
emit_load_imm(7, XOR_MASK)
emit_xor(6, 6, 7)

# Call round function subroutine: F(r1=W1, r6=key) -> r7
round_func_call = emit_call_placeholder()

# Restore words
emit_pop(3)
emit_pop(2)
emit_pop(1)
emit_pop(0)

# Feistel permutation: (W0, W1, W2, W3) -> (W1, W2, W3, W0 ^ F)
emit_xor(0, 0, 7)    # W0 = W0 ^ F(W1, K[i])
emit_mov(6, 0)        # temp = W0 ^ F
emit_mov(0, 1)        # new W0 = old W1
emit_mov(1, 2)        # new W1 = old W2
emit_mov(2, 3)        # new W2 = old W3
emit_mov(3, 6)        # new W3 = old W0 ^ F

# Restore loop counters, increment
emit_pop(5)
emit_pop(4)
emit_load_imm(6, 1)
emit_add(4, 4, 6)
emit_cmp(4, 5)
loop_back = emit_jne_placeholder()
patch_target(loop_back, loop_start)

# Store result words back to memory and output
emit_load_imm(7, 0x000)
emit_store_dword(0, 7)
emit_load_imm(7, 0x004)
emit_store_dword(1, 7)
emit_load_imm(7, 0x008)
emit_store_dword(2, 7)
emit_load_imm(7, 0x00C)
emit_store_dword(3, 7)

emit_load_imm(0, 0x000)
emit_load_imm(1, 16)
emit_syscall(2)  # write output
emit_syscall(3)  # halt

# === ROUND FUNCTION SUBROUTINE ===
round_func_addr = len(code)
patch_target(round_func_call, round_func_addr)

# F(x, k) = ROL(x, 7) ^ ROL(x, 13) ^ SHR(x, 3) ^ k
# Input: r1 = x (W1), r6 = k (round key)
# Output: r7 = F(x, k)
# Uses r4, r5 as temporaries (safe: caller's copies are on the stack)
emit_rol(4, 1, 7)     # r4 = ROL(x, 7)
emit_rol(5, 1, 13)    # r5 = ROL(x, 13)
emit_xor(4, 4, 5)     # r4 = ROL(x,7) ^ ROL(x,13)
emit_shr(5, 1, 3)     # r5 = x >> 3
emit_xor(4, 4, 5)     # r4 = ROL(x,7) ^ ROL(x,13) ^ SHR(x,3)
emit_xor(7, 4, 6)     # r7 = r4 ^ k
emit_ret()

# === DEAD CODE (decoy path, never reached for valid input) ===
dead_code_addr = len(code)
patch_target(dead_branch, dead_code_addr)

# Fake "alternative cipher" that just XORs with a constant
emit_load_imm(6, 0xDEADBEEF)
emit_xor(0, 0, 6)
emit_xor(1, 1, 6)
emit_xor(2, 2, 6)
emit_xor(3, 3, 6)
emit_load_imm(7, 0x000)
emit_store_dword(0, 7)
emit_load_imm(7, 0x004)
emit_store_dword(1, 7)
emit_load_imm(7, 0x008)
emit_store_dword(2, 7)
emit_load_imm(7, 0x00C)
emit_store_dword(3, 7)
emit_load_imm(0, 0x000)
emit_load_imm(1, 16)
emit_syscall(2)
emit_syscall(3)

# Add some nop padding for realism
for _ in range(16):
    emit_nop()

with open('/app/program.bin', 'wb') as f:
    f.write(bytes(code))

print(f"Generated program.bin: {len(code)} bytes")
