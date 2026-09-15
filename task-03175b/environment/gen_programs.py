#!/usr/bin/env python3
"""Generate Intel 8086 test binary programs for the simulator task.

Each program is hand-assembled raw 8086 machine code (bits 16, no headers).
"""

import os

OUTDIR = "/app/programs"
os.makedirs(OUTDIR, exist_ok=True)

programs = {
    # Program 1: Immediate MOV to all 8 general-purpose registers
    # Tests: B8+r imm16 encoding
    "imm_movs.bin": bytes([
        0xB8, 0x01, 0x00,  # mov ax, 1
        0xBB, 0x02, 0x00,  # mov bx, 2
        0xB9, 0x03, 0x00,  # mov cx, 3
        0xBA, 0x04, 0x00,  # mov dx, 4
        0xBC, 0x05, 0x00,  # mov sp, 5
        0xBD, 0x06, 0x00,  # mov bp, 6
        0xBE, 0x07, 0x00,  # mov si, 7
        0xBF, 0x08, 0x00,  # mov di, 8
    ]),

    # Program 2: Register-to-register arithmetic with flag effects
    # Tests: ADD r/m16,r16 (01), SUB r/m16,simm8 (83/5), CMP AX,imm16 (3D),
    #        MOV r/m16,r16 (89), SUB r/m16,r16 (29)
    "reg_arithmetic.bin": bytes([
        0xB8, 0x64, 0x00,        # mov ax, 100
        0xBB, 0x32, 0x00,        # mov bx, 50
        0x01, 0xD8,              # add ax, bx        ; ax=150
        0x83, 0xEB, 0x14,        # sub bx, 20        ; bx=30
        0x3D, 0x96, 0x00,        # cmp ax, 150       ; ZF=1
        0x89, 0xC1,              # mov cx, ax        ; cx=150
        0x89, 0xDA,              # mov dx, bx        ; dx=30
        0x29, 0xD1,              # sub cx, dx        ; cx=120
    ]),

    # Program 3: Fibonacci via loop (10 iterations)
    # Tests: JNZ rel8 (75), SUB r/m16,simm8 (83/5), MOV r/m16,r16 (89)
    # Computes F(10)=55, F(11)=89
    "fibonacci.bin": bytes([
        0xB9, 0x0A, 0x00,        # mov cx, 10        ; counter
        0xB8, 0x00, 0x00,        # mov ax, 0         ; F(n-1)
        0xBB, 0x01, 0x00,        # mov bx, 1         ; F(n)
        # fib_loop at offset 9:
        0x01, 0xD8,              # add ax, bx        ; ax = F(n-1)+F(n)
        0x89, 0xC2,              # mov dx, ax        ; dx = new F(n+1)
        0x89, 0xD8,              # mov ax, bx        ; ax = old F(n)
        0x89, 0xD3,              # mov bx, dx        ; bx = new F(n+1)
        0x83, 0xE9, 0x01,        # sub cx, 1
        0x75, 0xF3,              # jnz fib_loop      ; offset = 9-22 = -13
    ]),

    # Program 4: Direct memory addressing (load/store/accumulate)
    # Tests: MOV [moffs16],AX (A3), MOV r/m16,r16 with [disp16] (89),
    #        MOV r16,[disp16] (8B), ADD r/m16,r16 (01)
    "memory_ops.bin": bytes([
        0xB8, 0x34, 0x12,        # mov ax, 0x1234
        0xA3, 0x00, 0x02,        # mov [0x200], ax
        0xBB, 0x78, 0x56,        # mov bx, 0x5678
        0x89, 0x1E, 0x02, 0x02,  # mov [0x202], bx
        0x8B, 0x0E, 0x00, 0x02,  # mov cx, [0x200]   ; cx=0x1234
        0x8B, 0x16, 0x02, 0x02,  # mov dx, [0x202]   ; dx=0x5678
        0x01, 0xD1,              # add cx, dx        ; cx=0x68AC
        0x89, 0x0E, 0x04, 0x02,  # mov [0x204], cx
        0x8B, 0x36, 0x04, 0x02,  # mov si, [0x204]   ; si=0x68AC
    ]),

    # Program 5: Sum 1..100 with memory store and reload
    # Tests: loop, memory ops, borrow/carry flags
    # sum = 5050 = 0x13BA; 0x1000 - 0x13BA = 0xFC46 (CF=1, SF=1)
    "sum_challenge.bin": bytes([
        0xB9, 0x64, 0x00,        # mov cx, 100
        0xB8, 0x00, 0x00,        # mov ax, 0
        # sum_loop at offset 6:
        0x01, 0xC8,              # add ax, cx
        0x83, 0xE9, 0x01,        # sub cx, 1
        0x75, 0xF9,              # jnz sum_loop      ; offset = 6-13 = -7
        # offset 13:
        0x89, 0xC3,              # mov bx, ax        ; bx=5050
        0xBA, 0x00, 0x10,        # mov dx, 0x1000
        0x29, 0xC2,              # sub dx, ax        ; dx=0xFC46
        0x89, 0x16, 0x00, 0x03,  # mov [0x300], dx
        0x8B, 0x36, 0x00, 0x03,  # mov si, [0x300]   ; si=0xFC46
    ]),

    # Program 6: Indexed memory addressing with [BX+SI]
    # Tests: MOV r/m16,imm16 (C7/0), MOV r16,[BX+SI] (8B), ADD r/m16,simm8 (83/0)
    "indexed_memory.bin": bytes([
        0xBB, 0x00, 0x01,        # mov bx, 0x100
        0xBE, 0x00, 0x00,        # mov si, 0
        0xC7, 0x00, 0x0A, 0x0A,  # mov word [bx+si], 0x0A0A
        0x83, 0xC6, 0x02,        # add si, 2
        0xC7, 0x00, 0x0B, 0x0B,  # mov word [bx+si], 0x0B0B
        0x83, 0xC6, 0x02,        # add si, 2
        0xC7, 0x00, 0x0C, 0x0C,  # mov word [bx+si], 0x0C0C
        0xBE, 0x00, 0x00,        # mov si, 0
        0x8B, 0x00,              # mov ax, [bx+si]   ; ax=0x0A0A
        0x83, 0xC6, 0x02,        # add si, 2
        0x8B, 0x08,              # mov cx, [bx+si]   ; cx=0x0B0B
        0x01, 0xC8,              # add ax, cx        ; ax=0x1515
    ]),
}

for name, data in programs.items():
    path = os.path.join(OUTDIR, name)
    with open(path, "wb") as f:
        f.write(data)
    print(f"  {path} ({len(data)} bytes)")

print(f"Generated {len(programs)} test programs in {OUTDIR}")
