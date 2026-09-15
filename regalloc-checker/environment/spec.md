# Register Allocation Verification — Specification

## Problem

Given register-allocated programs stored in a SQLite database, determine whether each allocation is correct. An allocation is correct if and only if: at every point where an instruction reads a virtual register value from a physical register, that physical register holds the value of the expected virtual register on **all possible execution paths** reaching that point.

## Database

Programs are stored in `/app/programs.db`. Use `sqlite3 /app/programs.db` to explore interactively.

### Schema

**programs** — one row per program

| Column | Type | Description |
|--------|------|-------------|
| name | TEXT PK | Program identifier (e.g. `straight_line_correct`) |
| entry_block | TEXT | ID of the function entry block |
| phys_regs | TEXT | Comma-separated physical register names (e.g. `r0,r1,r2,r3`) |
| num_spill_slots | INTEGER | Number of stack spill slots, named `s0` through `s(N-1)` |

**blocks** — basic blocks within each program

| Column | Type | Description |
|--------|------|-------------|
| program_name | TEXT | FK → programs.name |
| block_id | TEXT | Block identifier |

**block_params** — SSA block parameters (phi-node semantics)

| Column | Type | Description |
|--------|------|-------------|
| program_name | TEXT | FK → blocks |
| block_id | TEXT | FK → blocks |
| param_idx | INTEGER | Parameter order (0-indexed) |
| vreg | TEXT | Virtual register name this parameter binds |
| preg | TEXT | Physical register that receives the value |

When control flows into a block with parameters, the predecessor's terminator passes arguments that bind to these parameters. At block entry, parameter bindings **override** whatever value was in the physical register from predecessor merging — they establish fresh, authoritative bindings.

**instructions** — ordered instructions within each block

| Column | Type | Description |
|--------|------|-------------|
| program_name | TEXT | FK → blocks |
| block_id | TEXT | FK → blocks |
| inst_idx | INTEGER | Execution order within the block (0-indexed) |
| kind | TEXT | One of: `op`, `spill`, `reload`, `move` |
| detail | TEXT | JSON-encoded instruction specifics (see below) |

**terminators** — one per block, controls outgoing edges

| Column | Type | Description |
|--------|------|-------------|
| program_name | TEXT | FK → blocks |
| block_id | TEXT | FK → blocks |
| kind | TEXT | One of: `return`, `jump`, `branch` |
| detail | TEXT | JSON-encoded terminator specifics (see below) |

### Instruction detail formats

**op** — arbitrary operation:
```json
{"kind":"op", "reads":[{"vreg":"v0","preg":"r0"}, ...], "writes":[{"vreg":"v1","preg":"r1"}, ...]}
```
- Each `read` declares: "this operation reads virtual register `vreg` from physical register `preg`" — the checker must verify this holds.
- Each `write` declares: "this operation produces virtual register `vreg` and places it in physical register `preg`" — this updates tracked state.

**spill** — copy physical register value to stack slot:
```json
{"kind":"spill", "src_preg":"r0", "dst_slot":0}
```
The spill slot receives whatever value the physical register currently holds.

**reload** — copy stack slot value back to physical register:
```json
{"kind":"reload", "src_slot":0, "dst_preg":"r0"}
```
The physical register receives whatever value the spill slot currently holds.

**move** — copy value between physical registers:
```json
{"kind":"move", "src_preg":"r0", "dst_preg":"r1"}
```
The destination receives whatever value the source currently holds.

### Terminator detail formats

**return** — end function, optionally reading values:
```json
{"kind":"return", "reads":[{"vreg":"v0","preg":"r0"}, ...]}
```
Each `read` is verified by the checker.

**jump** — unconditional transfer with arguments for the target block's parameters:
```json
{"kind":"jump", "target":"block_id", "args":[{"vreg":"v0","preg":"r0"}, ...]}
```
Each argument is verified: the physical register must hold the specified virtual register value.

**branch** — conditional with per-target arguments:
```json
{
  "kind":"branch",
  "cond":{"vreg":"v0","preg":"r0"},
  "true_target":"...", "true_args":[...],
  "false_target":"...", "false_args":[...]
}
```
The condition and all arguments are verified.

## Correctness Semantics

All physical registers and spill slots start in an **undefined** state at function entry.

**Writes** (from `op` instructions), **spills**, **reloads**, and **moves** update state as described above — they propagate concrete virtual register values (or propagate undefined/conflicted state from their source).

At a block with **multiple predecessors** (control-flow join), the state of each physical register and spill slot depends on all incoming paths:
- If all paths that reach the block agree on the same virtual register value for a location, that value holds.
- If different paths assign different virtual register values to the same location, that location's value is **conflicted** at that join.
- Locations that were never written on any reaching path remain **undefined**.

**Block parameters** override merged state — regardless of what predecessors contributed to a physical register, a parameter binding replaces it with a fresh virtual register value.

An **error** is reported when a verified read or argument finds:
- A different virtual register than expected
- A conflicted value (different values from different paths)
- An undefined value (never written on any reaching path)

## Output Format

### JSON verdict (stdout)

**Valid program:**
```json
{"valid": true, "errors": []}
```

**Invalid program:**
```json
{
  "valid": false,
  "errors": [
    {
      "block": "<block_id>",
      "instruction": <int_index_or_"terminator">,
      "preg": "<physical_register>",
      "expected_vreg": "<expected_vreg_name>",
      "actual": "<actual_vreg_name_or_unknown_or_conflicted>"
    }
  ]
}
```

Exit code: `0` for valid programs, `1` for invalid programs.

### DOT graph output

Write a Graphviz DOT file to `/app/output/<program_name>.dot` representing the program's control flow graph:
- Each block is a node labeled with its block ID
- Control flow edges connect blocks according to terminators (jump targets, branch targets)
- For invalid programs, blocks that contain errors must be visually distinguished using `color=red` or `fillcolor=red`
- The file must be valid input for `dot -Tsvg`

## Usage

```
python3 /app/regalloc_checker.py <program_name>
```

Where `<program_name>` matches a `name` in the `programs` table.
