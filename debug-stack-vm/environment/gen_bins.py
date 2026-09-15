#!/usr/bin/env python3
"""Generate correct .bin files and expected outputs for MiniStack-16 programs.
This script runs during Docker build and is deleted afterward.
It uses hardcoded correct byte sequences to avoid depending on assembler.py."""

import os
import struct


def le16(val):
    """Encode a 16-bit value in little-endian."""
    return struct.pack('<H', val & 0xFFFF)


def push(val):
    """Encode PUSH imm16 instruction (3 bytes)."""
    return bytes([0x01]) + le16(val)


def main():
    os.makedirs('/app/programs', exist_ok=True)
    os.makedirs('/app/expected', exist_ok=True)

    programs = {}

    # --- hello.bin ---
    # Simple character output: prints "Hello!\n"
    hello = bytearray()
    for ch in "Hello!\n":
        hello += push(ord(ch))
        hello += bytes([0x1E])  # PUTC
    hello += bytes([0xFF])  # HALT
    programs['hello'] = (bytes(hello), "Hello!\n")

    # --- fibonacci.bin ---
    # Print first 8 fibonacci numbers using memory for variables:
    #   mem[0xFF00] = a, mem[0xFF02] = b, mem[0xFF04] = counter
    fib = bytearray()
    # Init a = 1
    fib += push(1) + push(0xFF00) + bytes([0x1B])        # STORE
    # Init b = 1
    fib += push(1) + push(0xFF02) + bytes([0x1B])        # STORE
    # Init counter = 8
    fib += push(8) + push(0xFF04) + bytes([0x1B])        # STORE

    loop_addr = len(fib)  # 0x15 = 21

    # Print a
    fib += push(0xFF00) + bytes([0x1A, 0x1F])            # LOAD, PUTI
    fib += push(10) + bytes([0x1E])                       # PUTC newline

    # temp = a + b
    fib += push(0xFF00) + bytes([0x1A])                   # LOAD a
    fib += push(0xFF02) + bytes([0x1A])                   # LOAD b
    fib += bytes([0x06])                                   # ADD

    # a = old_b
    fib += push(0xFF02) + bytes([0x1A])                   # LOAD b
    fib += push(0xFF00) + bytes([0x1B])                   # STORE -> a = old_b

    # b = temp (still on stack from ADD)
    fib += push(0xFF02) + bytes([0x1B])                   # STORE -> b = temp

    # counter--
    fib += push(0xFF04) + bytes([0x1A])                   # LOAD counter
    fib += push(1) + bytes([0x07])                         # SUB
    fib += bytes([0x03])                                   # DUP
    fib += push(0xFF04) + bytes([0x1B])                   # STORE counter

    # JNZ loop
    jnz_addr = len(fib)
    jnz_offset = loop_addr - (jnz_addr + 3)
    fib += bytes([0x17]) + struct.pack('<h', jnz_offset)  # JNZ

    fib += bytes([0xFF])                                   # HALT
    programs['fibonacci'] = (bytes(fib), "1\n1\n2\n3\n5\n8\n13\n21\n")

    # --- signed_ops.bin ---
    # Tests signed operations: SHR (arithmetic), LT (signed), MOD (signed)
    signed = bytearray()

    # Test 1: arithmetic right shift: -16 >> 2 = -4
    signed += push(-16) + push(2) + bytes([0x11, 0x1F])  # SHR, PUTI
    signed += push(10) + bytes([0x1E])                     # PUTC newline

    # Test 2: signed less-than: -5 < 3 = 1
    signed += push(-5) + push(3) + bytes([0x13, 0x1F])   # LT, PUTI
    signed += push(10) + bytes([0x1E])                     # PUTC newline

    # Test 3: signed modulo: -7 % 3 = -1
    signed += push(-7) + push(3) + bytes([0x0A, 0x1F])   # MOD, PUTI
    signed += push(10) + bytes([0x1E])                     # PUTC newline

    signed += bytes([0xFF])                                # HALT
    programs['signed_ops'] = (bytes(signed), "-4\n1\n-1\n")

    # --- gcd.bin ---
    # Compute GCD(48, 18) = 6 using Euclidean algorithm
    gcd = bytearray()
    gcd += push(48) + push(18)

    gcd_loop = len(gcd)                                    # = 6
    gcd += bytes([0x03])                                   # DUP

    # JZ gcd_done (placeholder, filled later)
    jz_pos = len(gcd)
    gcd += bytes([0x16, 0x00, 0x00])                      # JZ placeholder

    gcd += bytes([0x04, 0x05, 0x0A])                      # SWAP, OVER, MOD

    # JMP gcd_loop
    jmp_pos = len(gcd)
    jmp_offset = gcd_loop - (jmp_pos + 3)
    gcd += bytes([0x15]) + struct.pack('<h', jmp_offset)  # JMP

    gcd_done = len(gcd)                                    # = 16
    gcd += bytes([0x02, 0x1F])                             # POP, PUTI
    gcd += push(10) + bytes([0x1E])                        # PUTC newline
    gcd += bytes([0xFF])                                   # HALT

    # Fill in JZ offset
    jz_offset = gcd_done - (jz_pos + 3)
    struct.pack_into('<h', gcd, jz_pos + 1, jz_offset)

    programs['gcd'] = (bytes(gcd), "6\n")

    # --- Write all binary files and expected outputs ---
    for name, (binary, expected) in programs.items():
        with open(f'/app/programs/{name}.bin', 'wb') as f:
            f.write(binary)
        with open(f'/app/expected/{name}.txt', 'w') as f:
            f.write(expected)
        print(f"  {name}.bin: {len(binary)} bytes")

    # --- Write selftest expected output ---
    # The solver writes selftest.asm that must produce this exact output.
    # Each line is the result of testing one instruction in order:
    # ADD, SUB, MUL, DIV, MOD, AND, OR, XOR, NOT, NEG,
    # SHL, SHR, EQ, LT, GT, DUP, OVER, LOAD/STORE
    selftest_expected = "\n".join([
        "300",    # ADD:  100 + 200
        "50",     # SUB:  80 - 30
        "600",    # MUL:  20 * 30
        "-3",     # DIV:  -7 / 2  (truncated toward zero)
        "-1",     # MOD:  -7 % 3  (signed)
        "15",     # AND:  0x0F0F & 0xF0FF = 0x000F
        "4080",   # OR:   0x0F00 | 0x00F0 = 0x0FF0
        "-3856",  # XOR:  0xFF00 ^ 0x0FF0 = 0xF0F0
        "-1",     # NOT:  ~0
        "-42",    # NEG:  -(42)
        "80",     # SHL:  5 << 4
        "-4",     # SHR:  -16 >> 2 (arithmetic)
        "1",      # EQ:   42 == 42
        "1",      # LT:   -1 < 1  (signed)
        "1",      # GT:   1 > -1  (signed)
        "14",     # DUP:  push 7, dup, add
        "40",     # OVER: push 10, push 20, over, add, add
        "999",    # LOAD/STORE: store 999, load back
    ]) + "\n"

    with open('/app/expected/selftest.txt', 'w') as f:
        f.write(selftest_expected)
    print("  selftest.txt: expected output")

    print(f"Generated {len(programs)} binary files and {len(programs)+1} expected outputs")


if __name__ == '__main__':
    main()
