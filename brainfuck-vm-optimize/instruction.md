A Brainfuck compiler and stack-based virtual machine are provided in Go at `/app/`. The system compiles Brainfuck source into a folded intermediate instruction set, then executes those instructions in a VM. However, the implementation contains correctness bugs and is too slow for complex programs.

## Correctness

Multiple test programs in `/app/testdata/` produce wrong output or hang indefinitely. Programs with nested loops give incorrect results. Programs relying on standard 8-bit wrapping cell semantics infinite-loop or crash. Investigate the compiler and VM source to find and fix the root causes.

## Performance

`/app/testdata/mandelbrot.b` must complete execution in under 20 seconds. The current implementation is orders of magnitude too slow. Analyze the compiled instruction stream (use `bfvm -dump <file.b>`) and the VM execution model to identify and eliminate the performance bottlenecks.

## Requirements

- Fix all correctness bugs so programs in `/app/testdata/` produce correct output without hanging.
- Optimize the compiler and VM so `/app/testdata/mandelbrot.b` completes within 20 seconds.
- All changes must be made to files under `/app/`.