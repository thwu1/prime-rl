An x86-64 assembler at `/app/` reads simplified assembly programs and emits JSON layout reports describing the final byte offsets of all items after jump encoding selection. The assembler compiles and runs but produces incorrect output for the assembly programs in `/app/programs/`.

The assembler's specification is at `/app/spec.md`. Fix the assembler so it produces correct JSON output for all programs. Rebuild with `make -C /app` after changes. Run:

    /app/assembler /app/programs/prog1.asm