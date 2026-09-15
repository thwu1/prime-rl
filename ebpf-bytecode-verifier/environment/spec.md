# BPF ELF Object Verification Specification

## Input Format

Programs are standard BPF ELF relocatable object files (`.o`). They use ELF64 little-endian format with `e_machine = EM_BPF (247)`.

### Analyzing ELF Structure

Use the installed analysis tools to inspect the object files:

- **`readelf -S -W <file>`** — list section headers. The `.text` section (flagged `AX`) holds the bytecode. The `.maps` section (flagged `A`) holds map descriptors if any. The `.bpf_meta` section holds program type metadata. Section offsets and sizes tell you where to extract data.
- **`llvm-objdump-18 -d <file>`** — disassemble BPF instructions from the `.text` section. Shows instruction offsets and mnemonics. Use `--no-show-raw-insn` to hide raw bytes.
- **`objcopy --dump-section .text=/tmp/out.bin <file>`** — extract raw bytes from a named section to a file.
- **`xxd <file>`** or **`hexdump -C <file>`** — raw hex inspection.

### Section Layout

| Section | Type | Flags | Content |
|---------|------|-------|---------|
| `.text` | PROGBITS | AX (alloc + exec) | BPF bytecode instructions |
| `.maps` | PROGBITS | A (alloc) | Map descriptors (if program uses maps) |
| `.bpf_meta` | PROGBITS | — | Program type metadata (1 byte) |
| `.shstrtab` | STRTAB | — | Section name strings |

### .bpf_meta Section

A single byte encoding the BPF program type:

| Value | Type |
|-------|------|
| `1` | XDP |
| `2` | kprobe |
| `3` | tracepoint |

### .maps Section (16 bytes per map entry)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 4 | map_id | Map identifier (u32 LE) |
| 4 | 4 | map_type | `1`=hash, `2`=array, `3`=prog_array (u32 LE) |
| 8 | 4 | key_size | Key size in bytes (u32 LE) |
| 12 | 4 | value_size | Value size in bytes (u32 LE) |

## BPF Instruction Encoding

The `.text` section contains a sequence of 8-byte BPF instructions:

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 1 | opcode | Instruction opcode |
| 1 | 1 | regs | `(src_reg << 4) \| dst_reg` — source in upper nibble, destination in lower |
| 2 | 2 | offset | Signed 16-bit offset (s16 LE) |
| 4 | 4 | imm | Signed 32-bit immediate (s32 LE) |

## Supported Opcodes

| Opcode | Mnemonic | Operands | Description |
|--------|----------|----------|-------------|
| `0xb7` | mov64_imm | dst, imm | `dst = imm` |
| `0xbf` | mov64_reg | dst, src | `dst = src` |
| `0xb4` | mov32_imm | dst, imm | `dst = (u32)imm` |
| `0x07` | add64_imm | dst, imm | `dst += imm` |
| `0x0f` | add64_reg | dst, src | `dst += src` |
| `0x17` | sub64_imm | dst, imm | `dst -= imm` |
| `0x57` | and64_imm | dst, imm | `dst &= imm` |
| `0x61` | ldx_w | dst, src, off | `dst = *(u32*)(src + off)` |
| `0x69` | ldx_h | dst, src, off | `dst = *(u16*)(src + off)` |
| `0x71` | ldx_b | dst, src, off | `dst = *(u8*)(src + off)` |
| `0x79` | ldx_dw | dst, src, off | `dst = *(u64*)(src + off)` |
| `0x62` | st_w | dst, off, imm | `*(u32*)(dst + off) = imm` |
| `0x7a` | st_dw | dst, off, imm | `*(u64*)(dst + off) = imm` |
| `0x73` | stx_b | dst, src, off | `*(u8*)(dst + off) = src` |
| `0x63` | stx_w | dst, src, off | `*(u32*)(dst + off) = src` |
| `0x6b` | stx_h | dst, src, off | `*(u16*)(dst + off) = src` |
| `0x7b` | stx_dw | dst, src, off | `*(u64*)(dst + off) = src` |
| `0x05` | ja | off | Unconditional jump to `PC + 1 + off` |
| `0x15` | jeq_imm | dst, imm, off | If `dst == imm`, jump to `PC + 1 + off` |
| `0x55` | jne_imm | dst, imm, off | If `dst != imm`, jump to `PC + 1 + off` |
| `0x2d` | jgt_reg | dst, src, off | If `dst > src`, jump to `PC + 1 + off` |
| `0x3d` | jge_reg | dst, src, off | If `dst >= src`, jump to `PC + 1 + off` |
| `0xad` | jlt_reg | dst, src, off | If `dst < src`, jump to `PC + 1 + off` |
| `0xbd` | jle_reg | dst, src, off | If `dst <= src`, jump to `PC + 1 + off` |
| `0x1d` | jeq_reg | dst, src, off | If `dst == src`, jump to `PC + 1 + off` |
| `0x5d` | jne_reg | dst, src, off | If `dst != src`, jump to `PC + 1 + off` |
| `0x85` | call | imm | Call helper function `imm` |
| `0x95` | exit | — | Terminate with R0 as return value |

## Registers

BPF programs use 11 registers (R0–R10):

| Register | Purpose |
|----------|---------|
| R0 | Function return value and program exit code |
| R1–R5 | Function arguments (clobbered by helper calls) |
| R6–R9 | Callee-saved registers (preserved across helpers) |
| R10 | Stack frame pointer (read-only, always PTR_TO_STACK) |

### Entry State

At program entry:
- R1 = PTR_TO_CTX (pointer to program context)
- R10 = PTR_TO_STACK (frame pointer, read-only)
- R0, R2–R9 = NOT_INIT (uninitialized)

## Register Type System

Each register carries a type:

| Type | Description |
|------|-------------|
| NOT_INIT | Uninitialized. Reading is an error. |
| SCALAR | Numeric value. Cannot be dereferenced. |
| PTR_TO_CTX | Pointer to program context (e.g., `xdp_md`). |
| PTR_TO_PACKET | Pointer to packet data (XDP only). |
| PTR_TO_PACKET_END | Pointer to end of packet data (XDP only). |
| PTR_TO_MAP_VALUE | Verified non-NULL pointer to a BPF map value. |
| PTR_TO_MAP_VALUE_OR_NULL | Pointer from map lookup; may be NULL. |
| PTR_TO_STACK | Stack frame pointer or derived. |

### Type Rules for Instructions

**Data movement:**
- `mov64_imm`, `mov32_imm`: result type is SCALAR.
- `mov64_reg`: result type copies source type.

**Arithmetic with immediate (`add64_imm`, `sub64_imm`, `and64_imm`):**
- PTR_TO_PACKET and PTR_TO_STACK are preserved; all other types become SCALAR.

**Arithmetic with register (`add64_reg`):**
- Both operands must be initialized. Result is SCALAR.

**Memory loads (`ldx_*`):**
Behavior depends on the source register type:
- PTR_TO_CTX: allowed. For XDP programs: offset 0 yields PTR_TO_PACKET (`ctx->data`), offset 4 yields PTR_TO_PACKET_END (`ctx->data_end`), other offsets yield SCALAR.
- PTR_TO_MAP_VALUE: allowed. Result: SCALAR.
- PTR_TO_STACK: allowed. Result: SCALAR.
- PTR_TO_PACKET: allowed **only if packet bounds have been verified on this execution path**. Result: SCALAR.
- PTR_TO_MAP_VALUE_OR_NULL: **error** (`null_ptr_deref`).
- SCALAR: **error** (`null_ptr_deref`).
- PTR_TO_PACKET_END: **error** (`null_ptr_deref`).
- NOT_INIT: **error** (`uninit_reg`).

**Memory stores (`st_*`, `stx_*`):**
- Destination must be PTR_TO_STACK or PTR_TO_MAP_VALUE. Dereferencing PTR_TO_MAP_VALUE_OR_NULL, SCALAR, or PTR_TO_PACKET_END through a store is an error (`null_ptr_deref`). NOT_INIT destination is `uninit_reg`. For `stx_*` variants, the source register must also be initialized.

**Helper calls (`call`):**
- Helper #1 (`bpf_map_lookup_elem`): sets R0 = PTR_TO_MAP_VALUE_OR_NULL.
- All other helpers: R0 = SCALAR.
- All calls clobber R1–R5 (become NOT_INIT). R6–R9 preserved. R10 unchanged.

**Conditional jumps:**
- All operand registers used in the comparison must be initialized.

## Verification Rules

The verifier must ensure that all safety properties hold on every possible execution path through the program. A register may have a different type at a given instruction depending on which execution path was taken to reach it.

### Rule 1: Register Initialization
Reading a NOT_INIT register is a violation.
**Rejection: `uninit_reg`**

### Rule 2: NULL Pointer Dereference
Dereferencing PTR_TO_MAP_VALUE_OR_NULL, SCALAR, or PTR_TO_PACKET_END is a violation.

After `bpf_map_lookup_elem` (helper #1), R0 is PTR_TO_MAP_VALUE_OR_NULL. A conditional comparison of such a register against 0 establishes type information for each branch:
- `jeq_imm R, 0, +off`: on the fall-through path (R != 0) the register is known non-NULL (PTR_TO_MAP_VALUE); on the jump-taken path (R == 0) it is known NULL (SCALAR).
- `jne_imm R, 0, +off`: on the jump-taken path (R != 0) the register is PTR_TO_MAP_VALUE; on the fall-through path (R == 0) it is SCALAR.

**Rejection: `null_ptr_deref`**

### Rule 3: Packet Bounds Verification
For XDP programs, loading from a PTR_TO_PACKET register requires that a bounds check has been performed on the current execution path.

The canonical bounds check: compute `check = data + N` (PTR_TO_PACKET + immediate preserves PTR_TO_PACKET), then `jgt_reg check, data_end, +off`. On the fall-through path (check <= data_end), packet access through any PTR_TO_PACKET register is permitted. On the jump-taken path, it is not.

**Rejection: `pkt_bounds`**

### Rule 4: No Loops
A backward edge (jump target index <= source instruction index) is a violation.
**Rejection: `loop`**

### Rule 5: Reachability
Every instruction must be reachable from the entry point (instruction 0).
**Rejection: `unreachable`**

### Rule 6: Exit Coverage
Every execution path must terminate with an `exit` instruction. A non-exit instruction that has no successors (falls off the end of the program) is a violation.
**Rejection: `no_exit`**

## Output Format

Print a single JSON object to stdout:

```json
{"verdict": "accept", "disasm": ["r0 = 2", "exit"]}
```
or
```json
{"verdict": "reject", "reason": "<category>", "disasm": ["r0 = r7", "exit"]}
```

Where `<category>` is one of: `uninit_reg`, `null_ptr_deref`, `pkt_bounds`, `loop`, `unreachable`, `no_exit`.

The `disasm` field must contain BPF instruction mnemonics extracted from the `.text` section using `llvm-objdump-18 -d --no-show-raw-insn`, one entry per instruction in order.
