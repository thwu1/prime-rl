# Simplified x86-like ISA Specification

## Assembly Syntax

- One instruction or directive per line
- Lines starting with `#` are comments; inline `#` comments are also supported
- Labels are identifiers followed by `:` on their own line (e.g., `loop:`)
- Whitespace before instructions/directives is optional
- Register operands: `r0` through `r7`
- Immediate operands: decimal integers (e.g., `42`, `-1`)
- Label operands: bare identifiers (e.g., `loop`, `end`)
- Operands are separated by commas with optional whitespace

## Registers

Eight general-purpose registers: `r0`, `r1`, `r2`, `r3`, `r4`, `r5`, `r6`, `r7`

## Fixed-size Instructions

| Mnemonic | Syntax          | Size (bytes) |
|----------|-----------------|:------------:|
| `nop`    | `nop`           | 1            |
| `ret`    | `ret`           | 1            |
| `push`   | `push rN`       | 2            |
| `pop`    | `pop rN`        | 2            |
| `mov`    | `mov rN, rM`    | 2            |
| `mov`    | `mov rN, imm`   | 3            |
| `add`    | `add rN, rM`    | 2            |
| `add`    | `add rN, imm`   | 3            |
| `sub`    | `sub rN, rM`    | 2            |
| `sub`    | `sub rN, imm`   | 3            |
| `cmp`    | `cmp rN, rM`    | 2            |
| `cmp`    | `cmp rN, imm`   | 3            |
| `call`   | `call label`    | 5            |

For `mov`, `add`, `sub`, and `cmp`: if the second operand matches `r[0-7]` it is a register operand (2-byte form); otherwise it is an immediate (3-byte form).

## Relaxable Jump Instructions

These instructions have two possible encodings. The assembler must choose the smallest valid encoding for each jump instruction such that the resulting layout is globally consistent.

| Mnemonic | Short Form | Long Form |
|----------|:----------:|:---------:|
| `jmp`    | 2 bytes    | 5 bytes   |
| `jz`     | 2 bytes    | 6 bytes   |
| `jnz`    | 2 bytes    | 6 bytes   |
| `jl`     | 2 bytes    | 6 bytes   |
| `jg`     | 2 bytes    | 6 bytes   |
| `jle`    | 2 bytes    | 6 bytes   |
| `jge`    | 2 bytes    | 6 bytes   |

### PC-relative Offset Calculation

The offset is measured from the **end** of the jump instruction to the target label:

```
offset = target_address - (instruction_address + instruction_size)
```

A jump can use the **short form** if and only if: **-128 <= offset <= 127**

Otherwise the **long form** must be used.

Note that `instruction_size` depends on which encoding is chosen, and `target_address` depends on the sizes of all preceding instructions—including any other jumps whose encoding choices may also be in question. The assembler must find an assignment of encodings where all offsets are consistent with their chosen forms.

## Directives

### `.align N`

Insert padding bytes so that the next item begins at an address that is a multiple of N. N must be a positive power of 2.

If the current offset is already a multiple of N, no padding is inserted.

Padding size = `(N - (current_offset % N)) % N`

### `.fill N`

Insert exactly N bytes of padding (N >= 0).

## Opcode Encoding

All instructions are encoded as one or more opcode bytes followed by operand bytes. Multi-byte integer values (immediates, PC-relative offsets) use **signed little-endian** byte order. Signed values use two's complement.

### Documented Encodings

| Instruction | Byte Encoding |
|------------|---------------|
| `nop` | `0x00` |
| `ret` | `0x01` |
| `jmp target` (short) | `0xE0, rel8` |
| `jz target` (short) | `0xE1, rel8` |
| `jnz target` (short) | `0xE2, rel8` |
| `jl target` (short) | `0xE3, rel8` |
| `jg target` (short) | `0xE4, rel8` |
| `jle target` (short) | `0xE5, rel8` |
| `jge target` (short) | `0xE6, rel8` |
| `jmp target` (long) | `0xF0, rel32` |
| Conditional jump (long) | `0x0F, ??, rel32` — the second byte varies by condition |

### Encoding Structure (Partially Documented)

For two-register instructions (`mov rN, rM`, `add rN, rM`, etc.), the format is: opcode byte, then a register-pair byte `(N << 4) | M`.

For register-immediate instructions (`mov rN, imm`, `add rN, imm`, etc.), the format is: opcode byte, register number byte `N`, then signed 8-bit immediate byte.

For `call label`, the format is: opcode byte, then signed 32-bit PC-relative offset (little-endian, measured from end of instruction).

### Undocumented

The specific opcode byte values for `push`, `pop`, `mov`, `add`, `sub`, `cmp`, and `call` are **not specified** in this document. The second opcode bytes for long-form conditional jumps are also omitted. The byte value used for `.fill`/`.align` padding is not specified.

Use the reference assembler's output modes (see `reference_asm -h`) to determine these values experimentally.
