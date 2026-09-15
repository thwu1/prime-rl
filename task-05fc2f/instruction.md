`/app/chibicc/` contains a built copy of [chibicc](https://github.com/rui314/chibicc), a small C11 compiler targeting x86-64 Linux. chibicc uses a stack-based code generation model: every binary operation pushes the first operand onto the hardware stack, evaluates the second operand, then pops — producing correct but heavily redundant assembly with many unnecessary `push`/`pop` pairs, no-op register moves, and superfluous jumps.

Create an executable at `/app/optimize` that reads an x86-64 assembly file (GNU AS syntax, as produced by `chibicc -S`) given as its first positional argument and writes optimized assembly to stdout. The optimizer must:

- **Preserve correctness**: optimized assembly must assemble with `as`, link with `gcc`, and produce identical runtime behavior (exit codes, output) to the unoptimized original for any valid C program chibicc can compile.
- **Achieve ≥10% instruction count reduction** (counting only actual instructions — not labels, directives, or comments) on programs of varying complexity including arithmetic expressions, function calls, loops, structs, and conditionals.
- **Handle control flow safely**: optimization must not cross label boundaries, break jump targets, corrupt the stack pointer, or interfere with floating-point stack operations.

Study chibicc's code generator at `/app/chibicc/codegen.c` and compile the example programs in `/app/examples/` with `/app/chibicc/chibicc -S -o output.s input.c` to understand redundancy patterns before designing your optimizer.