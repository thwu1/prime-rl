# Cpu0 ISA and Toolchain Specification

## Overview

Cpu0 is a 32-bit RISC processor with the following characteristics:
- Fixed 32-bit instruction width
- 16 general-purpose registers (GPR)
- Separate HI/LO registers for multiply/divide results
- Big-endian byte ordering
- Byte-addressable memory

## Register File

| Number | Name   | Alias  | Description                     |
|--------|--------|--------|---------------------------------|
| 0      | $zero  | $0     | Hardwired to zero (writes ignored) |
| 1      | $at    | $1     | Assembler temporary             |
| 2      | $v0    | $2     | Return value 0                  |
| 3      | $v1    | $3     | Return value 1                  |
| 4      | $a0    | $4     | Function argument 0             |
| 5      | $a1    | $5     | Function argument 1             |
| 6      | $t9    | $6     | Temporary / indirect call       |
| 7      | $t0    | $7     | Temporary 0                     |
| 8      | $t1    | $8     | Temporary 1                     |
| 9      | $s0    | $9     | Callee-saved 0                  |
| 10     | $s1    | $10    | Callee-saved 1                  |
| 11     | $gp    | $11    | Global pointer                  |
| 12     | $fp    | $12    | Frame pointer                   |
| 13     | $sp    | $13    | Stack pointer                   |
| 14     | $lr    | $14    | Link register                   |
| 15     | $sw    | $15    | Status word register            |

Special registers (not part of GPR file):
- **HI**: High 32 bits of multiply result, or remainder of divide
- **LO**: Low 32 bits of multiply result, or quotient of divide

## Instruction Formats

All instructions are 32 bits wide. There are three encoding formats:

### L-type (Load/Immediate)

```
 31      24 23  20 19  16 15                 0
+----------+------+------+------------------+
|  opcode  |  Ra  |  Rb  |      Cx (16)     |
+----------+------+------+------------------+
     8        4      4          16
```

### A-type (Arithmetic)

```
 31      24 23  20 19  16 15  12 11          0
+----------+------+------+------+------------+
|  opcode  |  Ra  |  Rb  |  Rc  |  Cx (12)  |
+----------+------+------+------+------------+
     8        4      4      4        12
```

### J-type (Jump)

```
 31      24 23                              0
+----------+--------------------------------+
|  opcode  |          Cx (24)               |
+----------+--------------------------------+
     8                  24
```

## Instruction Set

### Load/Store Instructions (L-type)

| Mnemonic | Opcode | Syntax              | Operation                          |
|----------|--------|---------------------|------------------------------------|
| LD       | 0x01   | LD Ra, Cx(Rb)       | Ra = mem32[Rb + sign_ext(Cx)]      |
| ST       | 0x02   | ST Ra, Cx(Rb)       | mem32[Rb + sign_ext(Cx)] = Ra      |
| LB       | 0x03   | LB Ra, Cx(Rb)       | Ra = sign_ext(mem8[Rb + sign_ext(Cx)]) |
| LBu      | 0x04   | LBu Ra, Cx(Rb)      | Ra = zero_ext(mem8[Rb + sign_ext(Cx)]) |
| SB       | 0x05   | SB Ra, Cx(Rb)       | mem8[Rb + sign_ext(Cx)] = Ra[7:0]  |
| LH       | 0x06   | LH Ra, Cx(Rb)       | Ra = sign_ext(mem16[Rb + sign_ext(Cx)]) |
| LHu      | 0x07   | LHu Ra, Cx(Rb)      | Ra = zero_ext(mem16[Rb + sign_ext(Cx)]) |
| SH       | 0x08   | SH Ra, Cx(Rb)       | mem16[Rb + sign_ext(Cx)] = Ra[15:0] |

### Immediate Arithmetic/Logic Instructions (L-type)

| Mnemonic | Opcode | Syntax              | Operation                          |
|----------|--------|---------------------|------------------------------------|
| ADDiu    | 0x09   | ADDiu Ra, Rb, Cx    | Ra = Rb + sign_ext(Cx)             |
| ANDi     | 0x0C   | ANDi Ra, Rb, Cx     | Ra = Rb & zero_ext(Cx)             |
| ORi      | 0x0D   | ORi Ra, Rb, Cx      | Ra = Rb \| zero_ext(Cx)            |
| XORi     | 0x0E   | XORi Ra, Rb, Cx     | Ra = Rb ^ zero_ext(Cx)             |
| LUi      | 0x0F   | LUi Ra, Cx          | Ra = Cx << 16 (Rb=0 in encoding)   |

### Set Less Than Immediate (L-type)

| Mnemonic | Opcode | Syntax              | Operation                          |
|----------|--------|---------------------|------------------------------------|
| SLTi     | 0x26   | SLTi Ra, Rb, Cx     | Ra = (Rb < sign_ext(Cx)) ? 1 : 0 (signed) |
| SLTiu    | 0x27   | SLTiu Ra, Rb, Cx    | Ra = (Rb < sign_ext(Cx)) ? 1 : 0 (unsigned) |

### Branch Instructions (L-type)

| Mnemonic | Opcode | Syntax              | Operation                          |
|----------|--------|---------------------|------------------------------------|
| BEQ      | 0x37   | BEQ Ra, Rb, Cx      | if (Ra == Rb) PC = PC + 4 + sign_ext(Cx) |
| BNE      | 0x38   | BNE Ra, Rb, Cx      | if (Ra != Rb) PC = PC + 4 + sign_ext(Cx) |

### Register Arithmetic Instructions (A-type)

| Mnemonic | Opcode | Syntax              | Operation                          |
|----------|--------|---------------------|------------------------------------|
| ADDu     | 0x11   | ADDu Ra, Rb, Rc     | Ra = Rb + Rc                       |
| SUBu     | 0x12   | SUBu Ra, Rb, Rc     | Ra = Rb - Rc                       |
| ADD      | 0x13   | ADD Ra, Rb, Rc      | Ra = Rb + Rc (with overflow trap)  |
| SUB      | 0x14   | SUB Ra, Rb, Rc      | Ra = Rb - Rc (with overflow trap)  |
| MUL      | 0x17   | MUL Ra, Rb, Rc      | Ra = (Rb * Rc)[31:0]               |

### Bit Manipulation Instructions (A-type)

| Mnemonic | Opcode | Syntax              | Operation                          |
|----------|--------|---------------------|------------------------------------|
| CLZ      | 0x15   | CLZ Ra, Rb          | Ra = count_leading_zeros(Rb)       |
| CLO      | 0x16   | CLO Ra, Rb          | Ra = count_leading_ones(Rb)        |

### Logic Instructions (A-type)

| Mnemonic | Opcode | Syntax              | Operation                          |
|----------|--------|---------------------|------------------------------------|
| AND      | 0x18   | AND Ra, Rb, Rc      | Ra = Rb & Rc                       |
| OR       | 0x19   | OR Ra, Rb, Rc       | Ra = Rb \| Rc                      |
| XOR      | 0x1A   | XOR Ra, Rb, Rc      | Ra = Rb ^ Rc                       |
| NOR      | 0x1B   | NOR Ra, Rb, Rc      | Ra = ~(Rb \| Rc)                   |

### Shift/Rotate Immediate Instructions (A-type)

These use the Cx field (12-bit) for the shift amount. Rc is 0 in the encoding.

| Mnemonic | Opcode | Syntax              | Operation                          |
|----------|--------|---------------------|------------------------------------|
| ROL      | 0x1C   | ROL Ra, Rb, Cx      | Ra = rotate_left(Rb, Cx)           |
| ROR      | 0x1D   | ROR Ra, Rb, Cx      | Ra = rotate_right(Rb, Cx)          |
| SHL      | 0x1E   | SHL Ra, Rb, Cx      | Ra = Rb << Cx                      |
| SHR      | 0x1F   | SHR Ra, Rb, Cx      | Ra = Rb >> Cx (logical, zero-fill) |
| SRA      | 0x20   | SRA Ra, Rb, Cx      | Ra = Rb >> Cx (arithmetic, sign-fill) |

### Shift/Rotate Register Instructions (A-type)

| Mnemonic | Opcode | Syntax              | Operation                          |
|----------|--------|---------------------|------------------------------------|
| SRAV     | 0x21   | SRAV Ra, Rb, Rc     | Ra = Rb >> Rc (arithmetic)         |
| SHLV     | 0x22   | SHLV Ra, Rb, Rc     | Ra = Rb << Rc                      |
| SHRV     | 0x23   | SHRV Ra, Rb, Rc     | Ra = Rb >> Rc (logical)            |
| ROLV     | 0x24   | ROLV Ra, Rb, Rc     | Ra = rotate_left(Rb, Rc)           |
| RORV     | 0x25   | RORV Ra, Rb, Rc     | Ra = rotate_right(Rb, Rc)          |

### Set Less Than Register Instructions (A-type)

| Mnemonic | Opcode | Syntax              | Operation                          |
|----------|--------|---------------------|------------------------------------|
| SLT      | 0x28   | SLT Ra, Rb, Rc      | Ra = (Rb < Rc) ? 1 : 0 (signed)   |
| SLTu     | 0x29   | SLTu Ra, Rb, Rc     | Ra = (Rb < Rc) ? 1 : 0 (unsigned) |

### Compare Instructions (A-type)

| Mnemonic | Opcode | Syntax              | Operation                          |
|----------|--------|---------------------|------------------------------------|
| CMP      | 0x2A   | CMP Ra, Rb          | SW flags: if Ra>Rb: N=0,Z=0; Ra<Rb: N=1,Z=0; Ra==Rb: N=0,Z=1 (signed) |
| CMPu     | 0x2B   | CMPu Ra, Rb         | Same as CMP but unsigned comparison |

SW register flag layout: bit 31 = N (negative), bit 30 = Z (zero).

### Multiply/Divide Instructions (A-type)

| Mnemonic | Opcode | Syntax              | Operation                          |
|----------|--------|---------------------|------------------------------------|
| MULT     | 0x41   | MULT Ra, Rb         | {HI, LO} = Ra * Rb (signed 64-bit)|
| MULTu    | 0x42   | MULTu Ra, Rb        | {HI, LO} = Ra * Rb (unsigned 64-bit)|
| DIV      | 0x43   | DIV Ra, Rb          | LO = Ra / Rb, HI = Ra % Rb (signed, truncate toward zero) |
| DIVU     | 0x44   | DIVU Ra, Rb         | LO = Ra / Rb, HI = Ra % Rb (unsigned) |

### HI/LO Move Instructions (A-type)

| Mnemonic | Opcode | Syntax              | Operation                          |
|----------|--------|---------------------|------------------------------------|
| MFHI     | 0x46   | MFHI Ra             | Ra = HI                           |
| MFLO     | 0x47   | MFLO Ra             | Ra = LO                           |
| MTHI     | 0x48   | MTHI Ra             | HI = Ra                           |
| MTLO     | 0x49   | MTLO Ra             | LO = Ra                           |

### Conditional Jump Instructions (J-type)

These test the SW register flags set by CMP/CMPu.

| Mnemonic | Opcode | Syntax              | Operation                          |
|----------|--------|---------------------|------------------------------------|
| JEQ      | 0x30   | JEQ Cx              | if Z==1: PC = PC + 4 + sign_ext(Cx) |
| JNE      | 0x31   | JNE Cx              | if Z==0: PC = PC + 4 + sign_ext(Cx) |
| JLT      | 0x32   | JLT Cx              | if N==1: PC = PC + 4 + sign_ext(Cx) |
| JGT      | 0x33   | JGT Cx              | if N==0 and Z==0: PC = PC + 4 + sign_ext(Cx) |
| JLE      | 0x34   | JLE Cx              | if N==1 or Z==1: PC = PC + 4 + sign_ext(Cx) |
| JGE      | 0x35   | JGE Cx              | if N==0: PC = PC + 4 + sign_ext(Cx) |

### Unconditional Jump/Call Instructions

| Mnemonic | Opcode | Format | Syntax        | Operation                          |
|----------|--------|--------|---------------|------------------------------------|
| JMP      | 0x36   | J      | JMP Cx        | PC = PC + 4 + sign_ext(Cx)         |
| JALR     | 0x39   | A      | JALR Rb       | LR = PC + 4; PC = Rb               |
| BAL      | 0x3A   | J      | BAL Cx        | LR = PC + 4; PC = PC + 4 + sign_ext(Cx) |
| JSUB     | 0x3B   | J      | JSUB Cx       | LR = PC + 4; PC = PC + 4 + sign_ext(Cx) |
| JR       | 0x3C   | A      | JR Ra         | PC = Ra                            |
| RET      | 0x3C   | A      | RET Ra        | Same as JR (alias)                 |

### Special Instructions

| Mnemonic | Opcode | Format | Operation                          |
|----------|--------|--------|------------------------------------|
| NOP      | 0x00   | L      | No operation (all zeros)           |

## Execution Model

### PC Advancement

1. Fetch the 32-bit instruction at address `PC`.
2. Compute `next_PC = PC + 4`.
3. Execute the instruction. Branch/jump instructions may override `next_PC`.
4. Set `PC = next_PC`.

### Branch Offset Computation

For all branch and jump instructions with immediate offsets:
- The offset (`Cx`) is **sign-extended** to 32 bits.
- The target address is: `PC + 4 + sign_ext(Cx)`, where PC is the address of the branch instruction itself.
- The assembler computes: `Cx = target_address - (branch_address + 4)`.

### Register $zero

Register $zero (r0) is hardwired to 0. All reads return 0; all writes are discarded.

### Integer Arithmetic

All arithmetic is 32-bit. Results are truncated to 32 bits (masked with 0xFFFFFFFF).
Signed operations interpret 32-bit values as two's complement.

## Memory Model

- **Size**: 65536 bytes (64 KB), addresses 0x0000 to 0xFFFF.
- **Byte order**: Big-endian.
- **Word access** (LD/ST): 4 bytes at the given address.
- **Halfword access** (LH/LHu/SH): 2 bytes at the given address.
- **Byte access** (LB/LBu/SB): 1 byte at the given address.
- Code is loaded at address 0x0000.

## Assembly Syntax

```
; Comments start with semicolon
label_name:                    ; Label definition
    mnemonic op1, op2, op3     ; Instruction with operands
    ld $v0, 8($sp)             ; Memory operand: offset($register)
    addiu $v0, $zero, -1       ; Negative immediate
    lui $v0, 0xABCD            ; Hexadecimal immediate
    beq $t0, $zero, label_name ; Branch to label
    jsub label_name            ; Jump to subroutine at label
    ret $lr                    ; Return (alias for jr $lr)
```

- Register names: `$zero`, `$at`, `$v0`, `$v1`, `$a0`, `$a1`, `$t9`, `$t0`, `$t1`, `$s0`, `$s1`, `$gp`, `$fp`, `$sp`, `$lr`, `$sw`, or by number `$0` to `$15`.
- Immediates: decimal (`42`, `-1`) or hexadecimal (`0xFF`, `0xABCD`).
- Memory operands: `offset($register)` where offset is an immediate.
- Labels: alphanumeric + underscore, followed by colon for definition.
- Case-insensitive mnemonics.

## Assembler Directives

| Directive | Syntax          | Description                                        |
|-----------|-----------------|----------------------------------------------------|
| .text     | .text           | Switch to the text (code) section. Default section. |
| .globl    | .globl symbol   | Mark a symbol as global (visible for cross-file linking). |

Directives are case-insensitive and may appear on their own line.

## ELF Object File Convention

The assembler must produce ELF32 relocatable object files conforming to:

### ELF Header Fields

- Class: ELFCLASS32 (1)
- Data encoding: ELFDATA2MSB (2) — big-endian
- OS/ABI: ELFOSABI_NONE (0)
- Type: ET_REL (1) for object files
- Machine: **EM_CPU0 = 201 (0xC9)**

### Required Sections

- `.text` (SHT_PROGBITS, SHF_ALLOC | SHF_EXECINSTR): Assembled machine code.
- `.symtab` (SHT_SYMTAB): Symbol table. Local symbols precede global symbols; `sh_info` gives the index of the first global symbol. `sh_link` points to `.strtab`.
- `.strtab` (SHT_STRTAB): String table for symbol names.
- `.shstrtab` (SHT_STRTAB): String table for section names.
- `.rel.text` (SHT_REL): Present when the file has unresolved external references. Uses ELF32 Rel entries (8 bytes each: `r_offset` + `r_info`). `sh_link` points to `.symtab`; `sh_info` gives the `.text` section index.

### Symbol Table Rules

- Labels marked with `.globl` have STB_GLOBAL binding.
- Labels not marked `.globl` have STB_LOCAL binding.
- Symbols referenced but not defined in the file: STB_GLOBAL with `st_shndx = SHN_UNDEF (0)`.
- The first entry (index 0) is the null symbol.

### Relocation Types

| Name         | Value | Applies to          | Calculation                     |
|--------------|-------|---------------------|---------------------------------|
| R_CPU0_PC24  | 1     | J-type (JSUB, BAL, JMP, etc.) | S - (P + 4), patched into 24-bit Cx field |
| R_CPU0_PC16  | 2     | L-type (BEQ, BNE)  | S - (P + 4), patched into 16-bit Cx field |
| R_CPU0_32    | 3     | Full word           | S, absolute 32-bit address      |

**S** = final symbol address after linking. **P** = address of the instruction containing the relocation.

`r_info` encoding: `(symbol_table_index << 8) | relocation_type`.

### Assembler Behavior

- References to labels **defined in the same file** are resolved at assembly time — no relocation emitted.
- References to labels **not defined in the file** generate a relocation entry and an undefined symbol in `.symtab`.

### Invocation

```
/app/cpu0asm <input.s> <output.o>
```

## Linker Specification

### Input
One or more ELF32 relocatable object files.

### Operation
1. Merge `.text` sections from all input files in command-line order, assigning contiguous addresses starting from 0.
2. Build a global symbol table. Duplicate global definitions are an error; every undefined reference must resolve to exactly one global definition.
3. Process all relocation entries using the formulas in the Relocation Types table.

### Output
An ELF32 big-endian executable with:
- Type: ET_EXEC (2)
- Machine: EM_CPU0 (0xC9)
- One PT_LOAD program header loading merged `.text` at virtual address 0
- Entry point (`e_entry`) = address of the `_start` global symbol

### Invocation
```
/app/cpu0ld -o <output> <input1.o> [input2.o ...]
```

## Simulator Specification

### Input
An ELF32 big-endian executable.

### Loading
Parse ELF header and program headers. For each PT_LOAD segment, load segment data into memory at its virtual address.

### Initialization
- PC = ELF `e_entry`
- r0 ($zero) = 0 (hardwired)
- r13 ($sp) = 0xFF00
- r14 ($lr) = 0xFFFFFFFF (halt sentinel)
- All other GPRs = 0
- HI = 0, LO = 0

### Halt Conditions
- PC >= end of loaded code
- More than 10,000,000 instructions executed

### Output
After halting, print all register values, one per line:
```
r0 = <value>
r1 = <value>
...
r15 = <value>
HI = <value>
LO = <value>
```
Values are unsigned 32-bit integers in decimal.

### Invocation
```
/app/cpu0sim <executable>
```
