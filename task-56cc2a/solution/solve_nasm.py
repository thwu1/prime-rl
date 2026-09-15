#!/usr/bin/env python3
"""
Generate NASM x86-64 test program, assemble, link, run, and produce
/app/ground_truth.json with hardware-validated division results.

"""

import json
import struct
import subprocess
import sys

NASM_SOURCE = """\
; x86-64 test program: validates 8086 division instruction behavior
; Assemble: nasm -f elf64 test_div.asm -o test_div.o
; Link:     ld test_div.o -o test_div
;
; Each test case loads DX:AX (or AX for byte) and a divisor,
; executes div/idiv, and stores quotient+remainder into a results buffer.
; The buffer is written to stdout as raw binary for Python to parse.
;
; NOTE: We use RBX (not R8-R15) as base pointer because AH cannot be
; encoded in instructions that require a REX prefix (R8-R15 do).

default rel

section .bss
    results: resb 64

section .text
    global _start

_start:
    lea rbx, [results]

    ; -- Test 0: unsigned word div  10 / 3 = 3 rem 1 --
    xor edx, edx            ; clear full RDX
    mov ax, 0x000A
    mov cx, 0x0003
    div cx                   ; DX:AX / CX -> AX=quot, DX=rem
    mov word [rbx+0], ax
    mov word [rbx+2], dx

    ; -- Test 1: unsigned word div  0x0F00:0xFF00 / 0x0FFC --
    xor edx, edx
    mov dx, 0x0F00
    mov ax, 0xFF00
    mov cx, 0x0FFC
    div cx
    mov word [rbx+4], ax
    mov word [rbx+6], dx

    ; -- Test 2: unsigned byte div  0x2345 / 0x34 --
    mov ax, 0x2345
    mov cl, 0x34
    div cl                   ; AX / CL -> AL=quot, AH=rem
    mov byte [rbx+8], al
    mov byte [rbx+9], ah

    ; -- Test 3: signed word div  -27 / 7 --
    mov dx, 0xFFFF
    mov ax, 0xFFE5
    mov cx, 0x0007
    idiv cx
    mov word [rbx+10], ax
    mov word [rbx+12], dx

    ; -- Test 4: signed word div  27 / -7 --
    xor edx, edx
    mov ax, 0x001B
    mov cx, 0xFFF9
    idiv cx
    mov word [rbx+14], ax
    mov word [rbx+16], dx

    ; -- Test 5: signed byte div  -27 / 7 --
    mov ax, 0xFFE5           ; AX as signed 16-bit = -27
    mov cl, 0x07
    idiv cl                  ; AX / CL -> AL=quot, AH=rem
    mov byte [rbx+18], al
    mov byte [rbx+19], ah

    ; -- Test 6: unsigned word div  0xFFFF / 1 (max quotient) --
    xor edx, edx
    mov ax, 0xFFFF
    mov cx, 0x0001
    div cx
    mov word [rbx+20], ax
    mov word [rbx+22], dx

    ; -- Write results buffer to stdout --
    mov rax, 1               ; sys_write
    mov rdi, 1               ; fd = stdout
    lea rsi, [results]
    mov rdx, 24              ; 24 bytes of results
    syscall

    ; -- Exit --
    mov rax, 60
    xor rdi, rdi
    syscall
"""


def main():
    # Write NASM source
    asm_path = '/app/test_div.asm'
    with open(asm_path, 'w') as f:
        f.write(NASM_SOURCE)
    print(f'Wrote NASM source to {asm_path}')

    # Assemble
    obj_path = '/app/test_div.o'
    print('Assembling with NASM...')
    subprocess.run(
        ['nasm', '-f', 'elf64', asm_path, '-o', obj_path],
        check=True,
    )
    print(f'  Object file: {obj_path}')

    # Link
    bin_path = '/app/test_div'
    print('Linking with ld...')
    subprocess.run(
        ['ld', obj_path, '-o', bin_path],
        check=True,
    )
    print(f'  Executable: {bin_path}')

    # Run and capture binary output
    print('Running test binary...')
    result = subprocess.run(
        [bin_path],
        capture_output=True,
        check=True,
    )
    data = result.stdout
    assert len(data) >= 24, f'Expected 24 bytes of output, got {len(data)}'
    print(f'  Captured {len(data)} bytes')

    # Parse binary results (all little-endian)
    test_vectors = []

    # Test 0: unsigned word, offsets 0-3
    q, r = struct.unpack_from('<HH', data, 0)
    test_vectors.append({
        'mode': 'word', 'signed': False,
        'dx': 0x0000, 'ax': 0x000A, 'divisor': 0x0003,
        'quotient': q, 'remainder': r,
    })

    # Test 1: unsigned word, offsets 4-7
    q, r = struct.unpack_from('<HH', data, 4)
    test_vectors.append({
        'mode': 'word', 'signed': False,
        'dx': 0x0F00, 'ax': 0xFF00, 'divisor': 0x0FFC,
        'quotient': q, 'remainder': r,
    })

    # Test 2: unsigned byte, offsets 8-9
    q, r = data[8], data[9]
    test_vectors.append({
        'mode': 'byte', 'signed': False,
        'dx': 0, 'ax': 0x2345, 'divisor': 0x34,
        'quotient': q, 'remainder': r,
    })

    # Test 3: signed word, offsets 10-13
    q, r = struct.unpack_from('<HH', data, 10)
    test_vectors.append({
        'mode': 'word', 'signed': True,
        'dx': 0xFFFF, 'ax': 0xFFE5, 'divisor': 0x0007,
        'quotient': q, 'remainder': r,
    })

    # Test 4: signed word, offsets 14-17
    q, r = struct.unpack_from('<HH', data, 14)
    test_vectors.append({
        'mode': 'word', 'signed': True,
        'dx': 0x0000, 'ax': 0x001B, 'divisor': 0xFFF9,
        'quotient': q, 'remainder': r,
    })

    # Test 5: signed byte, offsets 18-19
    q, r = data[18], data[19]
    test_vectors.append({
        'mode': 'byte', 'signed': True,
        'dx': 0, 'ax': 0xFFE5, 'divisor': 0x07,
        'quotient': q, 'remainder': r,
    })

    # Test 6: unsigned word, offsets 20-23
    q, r = struct.unpack_from('<HH', data, 20)
    test_vectors.append({
        'mode': 'word', 'signed': False,
        'dx': 0x0000, 'ax': 0xFFFF, 'divisor': 0x0001,
        'quotient': q, 'remainder': r,
    })

    # Write ground truth JSON
    gt_path = '/app/ground_truth.json'
    with open(gt_path, 'w') as f:
        json.dump({'test_vectors': test_vectors}, f, indent=2)

    print(f'\nGround truth written to {gt_path}:')
    for v in test_vectors:
        sign_str = 'signed' if v['signed'] else 'unsigned'
        print(f"  {v['mode']} {sign_str}: "
              f"({v['dx']:#06x}:{v['ax']:#06x}) / {v['divisor']:#06x} "
              f"= Q={v['quotient']:#06x} R={v['remainder']:#06x}")


if __name__ == '__main__':
    main()
