The directory `/app/chibicc/` contains a pre-built copy of chibicc, a small C11 compiler that generates correct but unoptimized x86-64 assembly. Its stack-based code generator produces many redundant instruction sequences — particularly unnecessary push/pop pairs for every binary operation and multi-instruction patterns that could be collapsed into single instructions.

Create a peephole optimizer at `/app/optimizer.py` that reads x86-64 AT&T syntax assembly from stdin and writes optimized assembly to stdout. The optimizer must:

- Preserve program semantics for any program chibicc can compile (correctness is non-negotiable — silent miscompilation is the worst outcome)
- Eliminate redundant instruction patterns in chibicc's generated assembly
- Achieve at least 12% total instruction count reduction on the benchmark program at `/app/benchmark.c`

You must reason carefully about which transformations are safe. Consider register aliasing (e.g., %edi is the lower 32 bits of %rdi), stack alignment requirements for function calls, and the interaction between optimizations across basic block boundaries.

Use `./chibicc -Iinclude -S -o FILE.s FILE.c` from within `/app/chibicc/` to generate assembly. Use `gcc FILE.s -o BINARY` to assemble and link. Verify correctness by confirming that optimized programs produce identical output to unoptimized versions.