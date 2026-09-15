Implement a Brainfuck compiler at `/app/bfc.py`. It must parse BF source, transform it into an optimized internal representation, and emit executable code through multiple backends.

## CLI

```
python3 /app/bfc.py run <file>       # Execute via optimized IR interpreter; raw output to stdout
python3 /app/bfc.py ir <file>        # Dump optimized IR to stdout, one instruction per line
python3 /app/bfc.py gen-c <file>     # Emit standalone C source to stdout
python3 /app/bfc.py gen-asm <file>   # Emit x86-64 assembly to stdout
python3 /app/bfc.py stats <file>     # Print optimization pass statistics
```

The target IR instruction set is documented at `/app/ir_spec.md`. The compiler must emit higher-level IR instructions wherever they are semantically equivalent to the input — a character-by-character lowering will not satisfy the test suite.

All execution paths — interpreter, compiled C, compiled assembly — must produce byte-identical output for any given program.

The C backend must emit a self-contained program that compiles with `gcc`. The assembly backend must emit x86-64 assembly that assembles with `as`, links with `gcc`, and produces a valid ELF executable with correct output.

BF cells are unsigned 8-bit with wrapping arithmetic. Tape has 30000 cells, zero-initialized. Test programs are at `/app/programs/`.