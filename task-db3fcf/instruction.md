A compiler toolchain for MiniCalc — a minimal imperative language with integer arithmetic, control flow, functions, and AWK-like variable scoping — is installed at `/opt/minicalc/`. It compiles `.mc` source files to JSON-serialized bytecode for a stack-based virtual machine. The compiled bytecode is a naive, unoptimized translation of the source.

Create `/app/optimizer.py` that reads compiled bytecode JSON and writes semantically-equivalent optimized bytecode:

```
python3 /app/optimizer.py <input.json> <output.json>
```

**Requirements:**

- For every `.mc` program in `/opt/minicalc/programs/`, the optimized bytecode must produce byte-for-byte identical output to the original when executed through the VM.
- Total instruction count across all benchmark programs must decrease by at least 15%.
- Function parameter lists in the output bytecode must be preserved unchanged.

The bytecode instruction set and VM semantics are documented in `/opt/minicalc/spec.md` and implemented in the toolchain source at `/opt/minicalc/`.