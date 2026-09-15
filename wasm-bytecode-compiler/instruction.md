Build an executable tool at `/app/wasm_abc` that compiles WebAssembly binary modules into an annotated fixed-width bytecode format with pre-resolved branch targets, executes the compiled bytecode, and identifies super-instruction fusion opportunities.

The annotated bytecode format specification is at `/app/ANNOTATED_BYTECODE_SPEC.md`. Test WASM modules are at `/app/modules/*.wasm` (compiled from WAT using `wabt`; source WAT is not available at runtime).

The tool must support two subcommands:

```
/app/wasm_abc compile <input.wasm> <output.json>
/app/wasm_abc run <input.wasm> <func_export_name> [i32_args...]
```

**`compile`**: Parse the WASM binary module, compile each function's instruction stream into the annotated format, detect super-instruction fusion candidates, and write a JSON report to the output path. The JSON format is specified in the spec document.

**`run`**: Compile and execute the annotated bytecode for the named exported function with the given i32 arguments. Print the i32 result to stdout as a plain integer.

The implementation must:

- Parse the WASM binary format (magic number, version, type/function/export/code sections)
- Decode LEB128-encoded immediates and expand them to fixed-width
- Correctly resolve branch targets for nested `block`/`loop`/`if`/`else` control flow, including multi-level `br`/`br_if` targeting outer constructs and `br_table` dispatch
- Elide structural opcodes (`block`, `loop`, `end`) from the output stream
- Handle the operand stack correctly during execution, including stack restoration on branches
- Support function calls with proper call stack and local variable isolation
- Handle the full opcode subset listed in the spec