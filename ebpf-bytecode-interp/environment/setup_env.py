#!/usr/bin/env python3
"""Generate sample programs and ISA reference for the BPF interpreter task."""
import os
import json
import struct

def bpf_insn(opcode, dst=0, src=0, off=0, imm=0):
    regs = ((src & 0xf) << 4) | (dst & 0xf)
    return struct.pack('<BBhi', opcode, regs, off, imm)

def bpf_ld_imm64(dst, val):
    lo = val & 0xFFFFFFFF
    hi = (val >> 32) & 0xFFFFFFFF
    lo_s = lo - 0x100000000 if lo >= 0x80000000 else lo
    hi_s = hi - 0x100000000 if hi >= 0x80000000 else hi
    return bpf_insn(0x18, dst, 0, 0, lo_s) + bpf_insn(0x00, 0, 0, 0, hi_s)

os.makedirs('/app/samples', exist_ok=True)

# Sample programs for development
samples = {
    "return_constant": {
        "description": "Returns constant 42",
        "hex": (bpf_insn(0xb7, 0, 0, 0, 42) + bpf_insn(0x95)).hex(),
        "expected_return": 42,
        "disassembly": ["r0 = 42", "exit"]
    },
    "add_numbers": {
        "description": "Computes 10 + 32 = 42",
        "hex": (
            bpf_insn(0xb7, 0, 0, 0, 10) +
            bpf_insn(0x07, 0, 0, 0, 32) +
            bpf_insn(0x95)
        ).hex(),
        "expected_return": 42,
        "disassembly": ["r0 = 10", "r0 += 32", "exit"]
    },
    "stack_roundtrip": {
        "description": "Store 42 on stack, load it back",
        "hex": (
            bpf_insn(0x7a, 10, 0, -8, 42) +
            bpf_insn(0x79, 0, 10, -8, 0) +
            bpf_insn(0x95)
        ).hex(),
        "expected_return": 42,
        "disassembly": [
            "*(u64 *)(r10 - 8) = 42",
            "r0 = *(u64 *)(r10 - 8)",
            "exit"
        ]
    },
    "branch_test": {
        "description": "If 5 > 3 return 1, else return 0",
        "hex": (
            bpf_insn(0xb7, 1, 0, 0, 5) +
            bpf_insn(0x25, 1, 0, 2, 3) +
            bpf_insn(0xb7, 0, 0, 0, 0) +
            bpf_insn(0x05, 0, 0, 1, 0) +
            bpf_insn(0xb7, 0, 0, 0, 1) +
            bpf_insn(0x95)
        ).hex(),
        "expected_return": 1,
        "disassembly": [
            "r1 = 5",
            "if r1 > 3 goto +2",
            "r0 = 0",
            "goto +1",
            "r0 = 1",
            "exit"
        ]
    },
    "multiply": {
        "description": "Computes 6 * 7 = 42",
        "hex": (
            bpf_insn(0xb7, 1, 0, 0, 6) +
            bpf_insn(0x27, 1, 0, 0, 7) +
            bpf_insn(0xbf, 0, 1, 0, 0) +
            bpf_insn(0x95)
        ).hex(),
        "expected_return": 42,
        "disassembly": ["r1 = 6", "r1 *= 7", "r0 = r1", "exit"]
    }
}

with open('/app/samples/sample_programs.json', 'w') as f:
    json.dump(samples, f, indent=2)

# ISA reference document
reference = """BPF Instruction Set Architecture - Quick Reference
===================================================

INSTRUCTION ENCODING (little-endian host)
-----------------------------------------
Basic instruction: 8 bytes
  byte 0:    opcode
  byte 1:    regs = (src_reg << 4) | dst_reg  [each 4 bits, 0-10]
  bytes 2-3: offset (signed 16-bit, little-endian)
  bytes 4-7: imm (signed 32-bit, little-endian)

Wide instruction (LD_IMM64 only): 16 bytes
  bytes 0-7:   basic instruction (opcode=0x18, src_reg=0)
  bytes 8-11:  reserved (all zeros)
  bytes 12-15: next_imm (signed 32-bit, little-endian)
  Result: dst = (next_imm << 32) | imm  (treating both as unsigned 32-bit halves)

INSTRUCTION CLASSES (lowest 3 bits of opcode)
----------------------------------------------
  LD=0x0  LDX=0x1  ST=0x2  STX=0x3  ALU=0x4  JMP=0x5  JMP32=0x6  ALU64=0x7

ALU/JMP OPCODE FORMAT
---------------------
  bits 7-4: code (operation)
  bit 3:    source (K=0 use imm, X=1 use src_reg)
  bits 2-0: class

ALU OPERATION CODES (4-bit 'code' field)
-----------------------------------------
  ADD=0x0  SUB=0x1  MUL=0x2  DIV=0x3  OR=0x4   AND=0x5  LSH=0x6  RSH=0x7
  NEG=0x8  MOD=0x9  XOR=0xa  MOV=0xb  ARSH=0xc END=0xd

  Common opcodes:
    MOV64_IMM  = 0xb7  (MOV, K, ALU64)    MOV64_REG  = 0xbf  (MOV, X, ALU64)
    ADD64_IMM  = 0x07  (ADD, K, ALU64)    ADD64_REG  = 0x0f  (ADD, X, ALU64)
    SUB64_IMM  = 0x17                     SUB64_REG  = 0x1f
    MUL64_IMM  = 0x27                     MUL64_REG  = 0x2f
    DIV64_IMM  = 0x37                     DIV64_REG  = 0x3f
    MOD64_IMM  = 0x97                     MOD64_REG  = 0x9f
    OR64_IMM   = 0x47                     OR64_REG   = 0x4f
    AND64_IMM  = 0x57                     AND64_REG  = 0x5f
    XOR64_IMM  = 0xa7                     XOR64_REG  = 0xaf
    LSH64_IMM  = 0x67                     RSH64_IMM  = 0x77
    ARSH64_IMM = 0xc7                     NEG64      = 0x87

    MOV32_IMM  = 0xb4  (MOV, K, ALU)      MOV32_REG  = 0xbc  (MOV, X, ALU)
    ADD32_IMM  = 0x04                     XOR32_REG  = 0xac
    ARSH32_IMM = 0xc4

ALU SEMANTICS
-------------
  ALU64 (class 0x7): operates on full 64-bit registers.
    For K (immediate): src_val = (s64)(s32)imm  (sign-extend 32->64)
    For X (register):  src_val = src_reg value

  ALU (class 0x4, 32-bit): operates on lower 32 bits.
    Result is ZERO-EXTENDED to 64 bits (upper 32 bits cleared).
    For K: src_val = (u32)imm
    For X: src_val = (u32)src_reg

  Division by zero: dst = 0
  Modulo by zero:
    ALU64: dst unchanged
    ALU:   upper 32 bits zeroed (same as normal ALU32 zero-extension)
  Shift mask: 0x3F for 64-bit, 0x1F for 32-bit
  NEG: dst = -dst (only defined with source=K)
  ARSH: arithmetic right shift (sign-preserving)

JMP OPERATION CODES
-------------------
  JA=0x0    JEQ=0x1   JGT=0x2   JGE=0x3   JSET=0x4  JNE=0x5
  JSGT=0x6  JSGE=0x7  CALL=0x8  EXIT=0x9  JLT=0xa   JLE=0xb
  JSLT=0xc  JSLE=0xd

  Common opcodes:
    JA         = 0x05  (JA, K, JMP)       offset = jump distance
    EXIT       = 0x95  (EXIT, K, JMP)
    JEQ_IMM    = 0x15                     JEQ_REG    = 0x1d
    JGT_IMM    = 0x25                     JGT_REG    = 0x2d
    JNE_IMM    = 0x55                     JNE_REG    = 0x5d
    JSGT_IMM   = 0x65                     JSGT_REG   = 0x6d

  Branch target: PC += offset + 1 (if taken), PC += 1 (if not taken)
  Unsigned comparisons: JGT, JGE, JLT, JLE
  Signed comparisons:   JSGT, JSGE, JSLT, JSLE
  JSET: taken if (dst & src) != 0

LOAD/STORE OPCODE FORMAT
-------------------------
  bits 7-5: mode (IMM=0, MEM=3)
  bits 4-3: size (W=0, H=1, B=2, DW=3)
  bits 2-0: class

  Common opcodes:
    LD_IMM64   = 0x18  (IMM, DW, LD)     -- wide instruction, 16 bytes
    LDX_MEM_B  = 0x71  (MEM, B, LDX)     LDX_MEM_H  = 0x69  (MEM, H, LDX)
    LDX_MEM_W  = 0x61  (MEM, W, LDX)     LDX_MEM_DW = 0x79  (MEM, DW, LDX)
    ST_MEM_B   = 0x72  (MEM, B, ST)      ST_MEM_H   = 0x6a  (MEM, H, ST)
    ST_MEM_W   = 0x62  (MEM, W, ST)      ST_MEM_DW  = 0x7a  (MEM, DW, ST)
    STX_MEM_B  = 0x73  (MEM, B, STX)     STX_MEM_H  = 0x6b  (MEM, H, STX)
    STX_MEM_W  = 0x63  (MEM, W, STX)     STX_MEM_DW = 0x7b  (MEM, DW, STX)

  LDX: dst = *(size *)(src_reg + offset)     [load from memory]
  ST:  *(size *)(dst_reg + offset) = imm     [store immediate]
  STX: *(size *)(dst_reg + offset) = src_reg [store register]

REGISTERS
---------
  R0:     return value
  R1-R5:  argument passing (caller-saved)
  R6-R9:  callee-saved
  R10:    frame pointer (read-only), points to top of 512-byte stack
          Valid stack access: [R10-512, R10)

PROGRAM EXECUTION
-----------------
  At start: R0-R9 = 0, R10 = frame pointer
  EXIT instruction returns the value of R0
"""

with open('/app/samples/bpf_isa_reference.txt', 'w') as f:
    f.write(reference)

print("Setup complete: created /app/samples/")
