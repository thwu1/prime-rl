# Annotated Bytecode Format Specification

## Overview

The annotated bytecode format transforms WebAssembly function bodies from the
standard variable-width LEB128 encoding into a fixed-width format optimized for
interpreter dispatch. Key properties:

1. All immediates are fixed-width (no LEB128 at runtime)
2. Structural opcodes (`block`, `loop`, `end`) are completely elided
3. Branch targets are pre-resolved to absolute byte offsets in the annotated stream
4. The format preserves execution semantics 1:1 with the original WASM

## Encoding Rules

### Simple Opcodes (no immediates)

Emit the single opcode byte unchanged.

Examples: `nop` (0x01), `unreachable` (0x00), `drop` (0x1a), `select` (0x1b),
`i32.add` (0x6a), `i32.sub` (0x6b), `i32.eqz` (0x45), etc.

### Immediate Expansion

All LEB128-encoded immediates are expanded to fixed-width little-endian:

| Immediate type | Width | Encoding |
|---|---|---|
| Local/global/function/type index | 4 bytes | u32 LE |
| i32.const value | 4 bytes | s32 LE (two's complement) |
| i64.const value | 8 bytes | s64 LE (two's complement) |

### Variable Access

- `local.get`: `[0x20][index:u32]` — 5 bytes
- `local.set`: `[0x21][index:u32]` — 5 bytes
- `local.tee`: `[0x22][index:u32]` — 5 bytes

### Constants

- `i32.const`: `[0x41][value:s32]` — 5 bytes
- `i64.const`: `[0x42][value:s64]` — 9 bytes

### Function Calls

- `call`: `[0x10][func_index:u32]` — 5 bytes
- `return`: `[0x0f]` — 1 byte

### Structural Opcodes (ELIDED)

The following opcodes emit **zero bytes** in the annotated stream:

- `block` (0x02) — elided, including its blocktype immediate
- `loop` (0x03) — elided, including its blocktype immediate
- `end` (0x0b) — elided

Their positions are tracked during compilation for branch target resolution but
produce no output bytes.

### Control Flow

**if**: `[0x04][false_pc:u32][end_pc:u32]` — 9 bytes

- Pops condition from operand stack
- If condition == 0: jump to `false_pc`
  - If an `else` clause exists: `false_pc` points to the first byte of the else body
  - If no `else` clause: `false_pc` == `end_pc`
- If condition != 0: continue execution (fall through to true body)
- `end_pc`: absolute offset of the first byte past the matching `end`

**else**: `[0x05][end_pc:u32]` — 5 bytes

- Unconditional jump to `end_pc`
- Reached when execution falls through the true body of an `if`

**br**: `[0x0c][target_pc:u32][arity:u32][restore_height:u32]` — 13 bytes

- Unconditional branch
- `target_pc`: absolute offset in annotated stream to jump to
- `arity`: number of values to preserve across the branch
- `restore_height`: operand stack height to restore to

**br_if**: `[0x0d][target_pc:u32][arity:u32][restore_height:u32]` — 13 bytes

- Conditional branch (pops condition; branches if non-zero)
- Same fields as `br`

**br_table**: `[0x0e][count:u32][entries...][default_entry]`

- `count`: number of non-default entries (u32, 4 bytes)
- Each entry: `[target_pc:u32][arity:u32][restore_height:u32]` — 12 bytes
- Total: 1 + 4 + (count + 1) * 12 bytes

### Branch Target Resolution

Branch targets resolve differently based on the construct they target:

| Target construct | `target_pc` resolves to |
|---|---|
| `block` | First byte after the block's matching `end` (forward jump) |
| `loop` | First byte of the loop body (backward jump to loop start) |
| `if` | First byte after the `if`'s matching `end` (forward jump) |
| function body | End of annotated stream (implicit return) |

### Branch Arity and Stack Restore

When branching:

1. Save top `arity` values from operand stack
2. Set operand stack height to `restore_height`
3. Push saved values back
4. Jump to `target_pc`

Arity is determined by the target construct's type:

- `block` / `if`: arity = number of result types (0 for void, 1 for single result)
- `loop`: arity = number of parameter types (typically 0)
- function body: arity = number of function result types

`restore_height` is the operand stack height at the point where the target
construct's body began execution.

## Supported Opcode Subset

### Control

| Opcode | Hex | Annotated encoding |
|---|---|---|
| unreachable | 0x00 | `[0x00]` (1 byte) |
| nop | 0x01 | `[0x01]` (1 byte) |
| block | 0x02 | elided |
| loop | 0x03 | elided |
| if | 0x04 | `[0x04][false_pc:u32][end_pc:u32]` |
| else | 0x05 | `[0x05][end_pc:u32]` |
| end | 0x0b | elided |
| br | 0x0c | `[0x0c][target_pc:u32][arity:u32][restore:u32]` |
| br_if | 0x0d | `[0x0d][target_pc:u32][arity:u32][restore:u32]` |
| br_table | 0x0e | `[0x0e][count:u32][entries][default]` |
| return | 0x0f | `[0x0f]` (1 byte) |

### Call

| Opcode | Hex | Annotated encoding |
|---|---|---|
| call | 0x10 | `[0x10][func_idx:u32]` (5 bytes) |

### Parametric

| Opcode | Hex | Annotated encoding |
|---|---|---|
| drop | 0x1a | `[0x1a]` (1 byte) |
| select | 0x1b | `[0x1b]` (1 byte) |

### Variable

| Opcode | Hex | Annotated encoding |
|---|---|---|
| local.get | 0x20 | `[0x20][idx:u32]` (5 bytes) |
| local.set | 0x21 | `[0x21][idx:u32]` (5 bytes) |
| local.tee | 0x22 | `[0x22][idx:u32]` (5 bytes) |

### Numeric (i32)

| Opcode | Hex | Annotated encoding |
|---|---|---|
| i32.const | 0x41 | `[0x41][val:s32]` (5 bytes) |
| i32.eqz | 0x45 | 1 byte |
| i32.eq | 0x46 | 1 byte |
| i32.ne | 0x47 | 1 byte |
| i32.lt_s | 0x48 | 1 byte |
| i32.lt_u | 0x49 | 1 byte |
| i32.gt_s | 0x4a | 1 byte |
| i32.gt_u | 0x4b | 1 byte |
| i32.le_s | 0x4c | 1 byte |
| i32.le_u | 0x4d | 1 byte |
| i32.ge_s | 0x4e | 1 byte |
| i32.ge_u | 0x4f | 1 byte |
| i32.clz | 0x67 | 1 byte |
| i32.ctz | 0x68 | 1 byte |
| i32.popcnt | 0x69 | 1 byte |
| i32.add | 0x6a | 1 byte |
| i32.sub | 0x6b | 1 byte |
| i32.mul | 0x6c | 1 byte |
| i32.div_s | 0x6d | 1 byte |
| i32.div_u | 0x6e | 1 byte |
| i32.rem_s | 0x6f | 1 byte |
| i32.rem_u | 0x70 | 1 byte |
| i32.and | 0x71 | 1 byte |
| i32.or | 0x72 | 1 byte |
| i32.xor | 0x73 | 1 byte |
| i32.shl | 0x74 | 1 byte |
| i32.shr_s | 0x75 | 1 byte |
| i32.shr_u | 0x76 | 1 byte |
| i32.rotl | 0x77 | 1 byte |
| i32.rotr | 0x78 | 1 byte |

### Numeric (i64)

| Opcode | Hex | Annotated encoding |
|---|---|---|
| i64.const | 0x42 | `[0x42][val:s64]` (9 bytes) |
| i64.eqz | 0x50 | 1 byte |
| i64.add | 0x7c | 1 byte |
| i64.sub | 0x7d | 1 byte |
| i64.mul | 0x7e | 1 byte |

### Conversion

| Opcode | Hex | Annotated encoding |
|---|---|---|
| i32.wrap_i64 | 0xa7 | 1 byte |
| i64.extend_i32_s | 0xac | 1 byte |
| i64.extend_i32_u | 0xad | 1 byte |

## Super-Instruction Fusion Patterns

The following instruction sequences are fusion candidates. Detection is greedy,
left-to-right, non-overlapping: when a pattern matches, the matched instructions
are consumed and detection continues after the last consumed instruction.

| Pattern name | Sequence | Fused count |
|---|---|---|
| `local_copy` | `local.get A; local.set B` | 2 |
| `i32_const_set` | `i32.const K; local.set A` | 2 |
| `i32_add_locals` | `local.get A; local.get B; i32.add` | 3 |
| `i32_sub_locals` | `local.get A; local.get B; i32.sub` | 3 |
| `i32_mul_locals` | `local.get A; local.get B; i32.mul` | 3 |
| `i32_cmp_locals` | `local.get A; local.get B; <i32_cmp>` | 3 |

Where `<i32_cmp>` is any of: `i32.eq`, `i32.ne`, `i32.lt_s`, `i32.lt_u`,
`i32.gt_s`, `i32.gt_u`, `i32.le_s`, `i32.le_u`, `i32.ge_s`, `i32.ge_u`.

Control-flow opcodes (`if`, `else`, `br`, `br_if`, `br_table`, `return`) break
fusion sequences — a pattern cannot span across them.

## JSON Report Format

The `compile` command must produce a JSON report with this structure:

```json
{
  "module": "<filename>",
  "functions": [
    {
      "index": 0,
      "export_name": "add",
      "param_count": 2,
      "local_count": 0,
      "original_code_bytes": 6,
      "annotated_bytes": 11,
      "expansion_ratio": 1.83,
      "branch_targets": {},
      "fusion_candidates": [
        {"offset": 0, "pattern": "i32_add_locals", "length": 3}
      ]
    }
  ],
  "summary": {
    "total_functions": 2,
    "total_original_bytes": 15,
    "total_annotated_bytes": 28,
    "total_fusion_candidates": 2,
    "average_expansion_ratio": 1.87
  }
}
```

Field definitions:

- `index`: function index within the module (0-based, includes imported functions in count)
- `export_name`: export name if exported, `null` otherwise
- `param_count`: number of function parameters
- `local_count`: number of declared local variables (excluding parameters)
- `original_code_bytes`: byte count of the original instruction stream including trailing `end`
- `annotated_bytes`: byte count of the compiled annotated stream
- `expansion_ratio`: `annotated_bytes / original_code_bytes` (rounded to 2 decimal places)
- `branch_targets`: dict mapping annotated stream offset (as string) to primary target offset (int)
  - For `if`: maps to `false_pc`
  - For `else`: maps to `end_pc`
  - For `br`/`br_if`: maps to `target_pc`
  - For `br_table`: maps to default `target_pc`
- `fusion_candidates`: list of detected patterns with offset in annotated stream, pattern name, and fused instruction count
- `summary.average_expansion_ratio`: `total_annotated_bytes / total_original_bytes` (rounded to 2 decimal places)
