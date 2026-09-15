The optimizing Brainfuck compiler at `/app/bfcomp.py` has two backends — a bytecode VM and an x86-64 NASM code generator — both of which are buggy or incomplete. Fix the compiler so that all five subcommands work correctly:

- `run <file.bf>` — execute via bytecode VM
- `bytecode <file.bf>` — print optimized bytecode listing
- `stats <file.bf>` — print optimization statistics as JSON (schema below)
- `asm <file.bf> <out.asm>` — generate x86-64 NASM assembly
- `build <file.bf> <out>` — compile to native Linux ELF executable (via `nasm -f elf64` + `ld`)

Both the bytecode VM and the generated native executables must produce identical, correct output for any valid BF program. Standard BF semantics: 30,000 byte cells, 0-255 wrapping, EOF sets cell to 0.

All optimization passes referenced in the source must be fully implemented and produce correct results in both backends. The NASM backend must emit efficient machine code for optimized ops (e.g., `mov byte [r13], 0` for SET_ZERO, `imul`/`add` sequences for MUL_COPY, loop-scan patterns for SCAN) rather than no-op stubs.

The environment has `nasm`, `ld`, and `objdump` installed for building and inspecting generated binaries.

Sample BF programs are in `/app/programs/`.

## `stats` JSON output schema

```
{
  "source_length":  <int>,   // count of BF instruction chars (><+-.,[]>) in source
  "bytecode_length": <int>,  // number of bytecode ops after all optimization passes
  "optimizations": {
    "contractions":        <int>,  // consecutive identical ops merged into one
    "cancellations":       <int>,  // adjacent opposite op pairs cancelled
    "clear_loops":         <int>,  // [-] and [+] patterns replaced with SET_ZERO
    "multiply_loops":      <int>,  // multiply/copy loop patterns detected and replaced
    "scan_loops":          <int>,  // pointer-only loop patterns replaced with SCAN
    "dead_code_eliminated": <int>  // unreachable loops eliminated after SET_ZERO
  }
}
```

All values are non-negative integers. The JSON must be parseable by `json.loads()`.

## `bytecode` listing format

One instruction per line:

```
<index>: <OPCODE> [<arg1> [<arg2>]]
```

Opcodes: `INC_PTR`, `DEC_PTR`, `INC_DATA`, `DEC_DATA`, `READ_STDIN`, `WRITE_STDOUT`, `JUMP_IF_ZERO`, `JUMP_IF_NONZERO`, `SET_ZERO`, `MUL_COPY`, `SCAN`.

`MUL_COPY <offset> <factor>` — adds `current_cell * factor` to cell at `ptr + offset`.
`SCAN <step>` — moves pointer by `step` until a zero cell is found.