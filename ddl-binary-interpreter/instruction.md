Build `/app/ddl_transpile.py`: a transpiler that reads DaeDaLus DDL binary format specifications and generates C source implementing the specified parsers. The transpiler accepts two positional arguments — a `.ddl` input path and a `.c` output path.

The DDL language subset is documented in `/app/SPEC.md`. The C runtime API is declared in `/app/runtime/parser.h` with implementation in `/app/runtime/runtime.c`. Study both to understand the available primitives and data structures. Four format specifications are in `/app/formats/` with corresponding binary test inputs in `/app/inputs/`. Use `xxd` to inspect the binary inputs alongside the DDL specs.

Transpile all four format specs (`container`, `tagged`, `choice`, `chunk_stream`) to C files in `/app/generated/`, then compile via the provided build system:

```
make -f /app/Makefile.template all
```

Each compiled parser takes a binary file path as its sole argument, writes parsed JSON to stdout on success (exit 0), and exits non-zero on malformed input.

All compiled parsers must be memory-clean. Validate with:

```
make -f /app/Makefile.template validate
```

This runs each parser under `valgrind --leak-check=full` and writes combined output to `/app/valgrind_report.txt`. All four parsers must show zero errors and zero leaks.