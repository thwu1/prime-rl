# Assembler Relaxation Engine — Specification

## Overview

The assembler at `/app/` reads simplified assembly programs and outputs JSON
layout reports describing the final assembled layout after iterative jump
relaxation.

### Source Files

| File | Role |
|---|---|
| `assembler.h` | Data structure definitions |
| `main.c` | Driver — reads file, calls parse/layout/output |
| `parser.c` | Assembly language parser |
| `layout.c` | Layout computation and jump relaxation |
| `output.c` | JSON output formatter |
| `Makefile` | Build system (`make` or `make debug`) |

## Assembly Language Syntax

The input is a text file with one statement per line. Blank lines and lines
where the first non-whitespace character is `;` or `#` are ignored (comments).

### Labels

A label is an identifier (`[A-Za-z_][A-Za-z0-9_]*`) followed by a colon (`:`),
optionally followed by a statement on the same line. A label marks the byte
offset of the next item in the program. Labels are case-sensitive and must be
unique within a program.

Examples:
```
start:
loop_end:
A: inst 2
```

### Statements

| Syntax | Description |
|---|---|
| `inst N` | A fixed-size instruction occupying exactly N bytes (1 ≤ N ≤ 10). |
| `jmp LABEL` | Unconditional jump to LABEL. |
| `jcc LABEL` | Conditional jump to LABEL. |
| `.fill N` | Insert N bytes of padding (N ≥ 0). |
| `.align N` | Pad with bytes to align the next item to an N-byte boundary. N must be a positive power of 2 (1, 2, 4, 8, 16, …). The padding size is `(N - (offset % N)) % N` where `offset` is the current byte offset. |

Mnemonics are case-insensitive. Labels and label references are case-sensitive.

## Jump Encoding

Both `jmp` and `jcc` have two possible encodings:

| Form | Size | Displacement range |
|---|---|---|
| **Short** | 2 bytes (1-byte opcode + 1-byte signed offset) | −128 to +127 |
| **Long** | Varies by instruction type | Effectively unlimited |

The **short** encoding is always 2 bytes for both unconditional and conditional
jumps.

The **long** encoding size differs between unconditional (`jmp`) and conditional
(`jcc`) jumps, reflecting different opcode structures in x86-64 near jump
encoding. Reference programs at `/app/ref/` demonstrate both short and long
forms and can be examined with standard GNU binutils tools.

The `Item.is_cond` field in `assembler.h` indicates whether a jump is
conditional (`true` for `jcc`, `false` for `jmp`).

The **displacement** of a jump is:

```
displacement = target_label_offset - (jump_offset + jump_size)
```

That is, the signed distance from the end of the jump instruction to the target
label. A short encoding requires −128 ≤ displacement ≤ 127.

## Relaxation Algorithm

The assembler starts with all jumps in **short** (2-byte) form and iteratively
relaxes jumps that cannot reach their targets:

1. Compute the byte offset of every item and label (the **layout**), including
   alignment padding which depends on current offsets.
2. For each jump still in short form, compute its displacement. If the
   displacement is outside [−128, +127], mark the jump for relaxation (switch
   to long form, using the appropriate size for its instruction type).
3. If any jump was relaxed in this pass, increment the iteration counter and go
   back to step 1 (recompute the entire layout with the new sizes).
4. When a pass makes no changes, the layout has converged.

**Important:** Relaxation is monotonic — once a jump is relaxed to long form, it
stays long. Jumps only grow; they never shrink back to short form.

### Why iteration is needed

Relaxing a jump increases the code size. This shifts all subsequent items
forward, which can:

- Push a label beyond the range of another short jump (forward reference cascade)
- Shift the offset at an `.align` directive, changing its padding size, which
  can amplify or dampen the shift for items after the alignment
- Push a backward-referenced label further away from a jump that refers to it

These cascading effects mean multiple passes may be needed before convergence.
The interaction between asymmetric jump sizes and alignment padding can create
subtle cascading patterns that only surface with specific program layouts.

## Data Structures

The `Program` struct (defined in `assembler.h`) stores items and labels:

- Each `Label` has an `item_index` field set by the parser to the item position
  the label precedes, and an `offset` field that the layout engine resolves to
  the corresponding byte offset.
- Each `Item` has `offset` and `size` fields resolved by the layout engine.
  For jumps, the `relaxed` flag controls encoding selection, and the `is_cond`
  flag indicates the instruction type.

The layout engine updates `Label.offset` for every label during layout
computation. Labels with `item_index == i` receive the byte offset of
item `i`. Labels with `item_index == num_items` point past the last item and
receive the total program size.

## Output Format

The output module (`output.c`) reads the computed offsets and sizes from the
`Program` struct and the iteration count from `LayoutResult`. It produces:

```json
{
  "total_size": <int>,
  "iterations": <int>,
  "labels": {
    "<name>": <int>,
    ...
  },
  "jumps": [
    {
      "line": <int>,
      "target": "<label_name>",
      "offset": <int>,
      "size": <int>,
      "relaxed": <bool>
    },
    ...
  ]
}
```

| Field | Description |
|---|---|
| `total_size` | Total size of the assembled program in bytes. |
| `iterations` | Number of relaxation passes that changed at least one jump. 0 if no relaxation was needed. |
| `labels` | Map of label name to its final byte offset. |
| `jumps` | List of jump instructions in source order, each with: `line` (1-indexed source line number), `target` (label name), `offset` (byte offset of the jump), `size` (encoding size in bytes), `relaxed` (true if long form, false if short form). |
