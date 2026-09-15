#!/usr/bin/env python3
"""Generate 6502 test binaries for cycle-count verification.

Each test is a small program that exercises specific instructions and traps.
The driver detects the trap and reports total cycles.
"""

import struct, os

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

def write_bin(name, code, load=0x0400):
    """Write a raw binary file."""
    path = os.path.join(TESTS_DIR, name)
    with open(path, 'wb') as f:
        f.write(bytes(code))
    return path

# Helper: create a self-trapping program (JMP to self at end)
def trap_at(pc):
    """JMP $pc (3 bytes: 4C lo hi)"""
    return [0x4C, pc & 0xFF, (pc >> 8) & 0xFF]

def make_test_nop_timing():
    """5 NOPs then trap. Expected: 5*2 + 3(JMP) = 13 cycles."""
    code = [0xEA] * 5  # NOP NOP NOP NOP NOP
    trap_pc = 0x0400 + len(code)
    code += trap_at(trap_pc)
    write_bin("test_nop_timing.bin", code)
    return 13

def make_test_lda_imm():
    """LDA #$42, LDA #$00, then trap. Expected: 2+2+3 = 7."""
    code = [0xA9, 0x42,  # LDA #$42
            0xA9, 0x00]  # LDA #$00
    trap_pc = 0x0400 + len(code)
    code += trap_at(trap_pc)
    write_bin("test_lda_imm.bin", code)
    return 7

def make_test_branch_taken():
    """CLC; BCC +0 (branch to next instr, taken, no page cross).
    CLC=2, BCC taken no cross=3, then trap JMP=3. Total=8."""
    code = [0x18,        # CLC
            0x90, 0x00]  # BCC +0 (branch to next byte)
    trap_pc = 0x0400 + len(code)
    code += trap_at(trap_pc)
    write_bin("test_branch_taken.bin", code)
    return 8

def make_test_branch_not_taken():
    """SEC; BCC +0 (not taken). SEC=2, BCC not taken=2, JMP=3. Total=7."""
    code = [0x38,        # SEC
            0x90, 0x00]  # BCC +0 (not taken because C=1)
    trap_pc = 0x0400 + len(code)
    code += trap_at(trap_pc)
    write_bin("test_branch_not_taken.bin", code)
    return 7

def make_test_stack_ops():
    """PHA, PLA, then trap. PHA=3, PLA=4, JMP=3. Total=10."""
    code = [0x48,  # PHA
            0x68]  # PLA
    trap_pc = 0x0400 + len(code)
    code += trap_at(trap_pc)
    write_bin("test_stack_ops.bin", code)
    return 10

def make_test_jsr_rts():
    """JSR to sub, sub does RTS, then trap.
    JSR=6, RTS=6, JMP=3. Total=15.
    Layout at $0400: JSR $0406; JMP $0403; RTS
    $0400: 20 06 04   JSR $0406
    $0403: 4C 03 04   JMP $0403 (trap)
    $0406: 60         RTS
    """
    code = [0x20, 0x06, 0x04,  # JSR $0406
            0x4C, 0x03, 0x04,  # JMP $0403 (trap)
            0x60]              # RTS
    write_bin("test_jsr_rts.bin", code)
    return 15

def make_test_abs_x_page_cross():
    """LDX #$FF; LDA $0400,X (crosses page -> 4+1=5). LDX=2, LDA=5, JMP=3. Total=10.
    Reads from $04FF which crosses from page $04 to... wait, $0400+$FF=$04FF, same page.
    Let's use LDA $0401,X with X=$FF -> $0500, crosses page.
    LDX #$FF (2 cycles), LDA $0401,X (5 cycles, page cross), JMP (3). Total=10."""
    code = [0xA2, 0xFF,        # LDX #$FF
            0xBD, 0x01, 0x04]  # LDA $0401,X -> $0500 (page cross)
    trap_pc = 0x0400 + len(code)
    code += trap_at(trap_pc)
    write_bin("test_abs_x_page_cross.bin", code)
    return 10

def make_test_abs_x_no_cross():
    """LDX #$01; LDA $0400,X (no page cross -> 4). LDX=2, LDA=4, JMP=3. Total=9."""
    code = [0xA2, 0x01,        # LDX #$01
            0xBD, 0x00, 0x04]  # LDA $0400,X -> $0401 (no cross)
    trap_pc = 0x0400 + len(code)
    code += trap_at(trap_pc)
    write_bin("test_abs_x_no_cross.bin", code)
    return 9

def make_test_zp_ops():
    """LDA #$42; STA $10; INC $10; LDA $10; trap.
    LDA_imm=2, STA_zp=3, INC_zp=5, LDA_zp=3, JMP=3. Total=16."""
    code = [0xA9, 0x42,  # LDA #$42
            0x85, 0x10,  # STA $10
            0xE6, 0x10,  # INC $10
            0xA5, 0x10]  # LDA $10
    trap_pc = 0x0400 + len(code)
    code += trap_at(trap_pc)
    write_bin("test_zp_ops.bin", code)
    return 16

def make_test_flag_ops():
    """SEC; CLC; SED; CLD; SEI; CLI; CLV. All 2 cycles each. 7*2=14 + JMP=3. Total=17."""
    code = [0x38,  # SEC
            0x18,  # CLC
            0xF8,  # SED
            0xD8,  # CLD
            0x78,  # SEI
            0x58,  # CLI
            0xB8]  # CLV
    trap_pc = 0x0400 + len(code)
    code += trap_at(trap_pc)
    write_bin("test_flag_ops.bin", code)
    return 17

# Generate all tests and write expected cycle counts
if __name__ == "__main__":
    tests = [
        ("test_nop_timing.bin", make_test_nop_timing()),
        ("test_lda_imm.bin", make_test_lda_imm()),
        ("test_branch_taken.bin", make_test_branch_taken()),
        ("test_branch_not_taken.bin", make_test_branch_not_taken()),
        ("test_stack_ops.bin", make_test_stack_ops()),
        ("test_jsr_rts.bin", make_test_jsr_rts()),
        ("test_abs_x_page_cross.bin", make_test_abs_x_page_cross()),
        ("test_abs_x_no_cross.bin", make_test_abs_x_no_cross()),
        ("test_zp_ops.bin", make_test_zp_ops()),
        ("test_flag_ops.bin", make_test_flag_ops()),
    ]

    # Write expected values file
    with open(os.path.join(TESTS_DIR, "expected_cycles.txt"), "w") as f:
        for name, cycles in tests:
            f.write(f"{name} {cycles}\n")

    print(f"Generated {len(tests)} cycle-count test binaries.")
