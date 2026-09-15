The file `/app/hack_pipeline.py` implements a correct Hack VM-to-machine-code pipeline: VM translator, assembler, and CPU emulator. The VM translator emits independent assembly templates per VM command with no cross-boundary optimization, producing correct but verbose output with significant redundancy at command boundaries.

An optimizer stub exists at `/app/optimizer.py` exporting `optimize_asm(lines: list[str]) -> list[str]`. It currently returns the input unchanged. Implement this function to perform peephole optimization on the generated Hack assembly.

The optimized assembly must produce identical RAM states to unoptimized assembly for every test program in `/app/vm_programs/`, including the multi-file recursive `FibonacciElement` directory (which requires bootstrap code and multi-file translation). All labels from the input must appear in the output. The optimizer must be idempotent (applying it twice produces the same result as once).

Instruction count reduction targets (counting non-label, non-empty lines):

| Program | Minimum reduction |
|---|---|
| SimpleAdd | 30% |
| StackTest | 25% |
| BasicTest | 15% |
| PointerTest | 25% |
| StaticTest | 25% |
| BasicLoop | 15% |
| FibonacciSeries | 15% |

The Hack ISA and VM language specification is at `/app/docs/hack_spec.txt`. Diagnostic tools at `/app/tools/` include a standalone CPU emulator with `--trace` mode and a binary diff/disassembler. Reference hand-written assembly programs and their known-correct binaries are at `/app/asm_programs/` and `/app/reference/`.