A MicroJava compiler and VM are installed at `/app/MicroJava/`. Three MicroJava programs have been compiled to `.obj` bytecode files in `/app/programs/`: `fold_and_shift.obj`, `control_flow.obj`, and `nested.obj` (corresponding `.mj` source files are alongside them).

Build a bytecode optimizer that reads a MicroJava `.obj` file and writes a smaller `.obj` file producing **byte-identical output** when executed on the MicroJava VM.

## .obj file format

Binary layout: `'M' 'J'` (2 bytes) | `codeSize` (4 bytes big-endian) | `dataSize` (4 bytes big-endian) | `mainPc` (4 bytes big-endian) | code bytes (`codeSize` bytes). Study `/app/MicroJava/MJ/Run.java` and `/app/MicroJava/MJ/CodeGen/Code.java` for the complete instruction set encoding, operand sizes, and file I/O logic.

## Deliverable

Place the optimizer at `/app/optimizer.py`, invokable as:

```
python3 /app/optimizer.py <input.obj> <output.obj>
```

The VM is invoked as `java -cp /app/MicroJava MJ.Run <file.obj>`.

Run the optimizer on all three programs in `/app/programs/`.

## Success criteria

- **Correctness**: Each optimized `.obj` must produce byte-identical output to the original when run on the VM.
- **Valid format**: Output must be a valid `.obj` — correct `MJ` signature, `codeSize` equal to the actual code byte count, non-negative `dataSize`, and `mainPc` within `[0, codeSize)`.
- **Size reduction**: Each optimized file must be strictly smaller than the original.
- **Minimum savings**: `fold_and_shift` must save at least 30 bytes, `control_flow` at least 15 bytes, `nested` at least 20 bytes.