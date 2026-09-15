The Mugo compiler at `/app/mugo.go` is a self-hosting compiler for a subset of Go that outputs x86-64 NASM assembly. It uses a naive stack-machine code generation strategy: every binary operation pushes operands onto the stack and pops them into registers, producing abundant redundant push/pop sequences. A pre-built binary is at `/app/mugo`.

Write `/app/optimizer.py` that reads NASM x86-64 assembly from stdin and writes optimized assembly to stdout. The optimizer must eliminate or replace redundant push/pop instruction pairs with more efficient alternatives (e.g., direct `mov` instructions or elimination of self-canceling push/pop pairs), while preserving identical runtime behavior for all test programs.

The optimizer must reduce total instruction count by at least 10% across the test programs in `/app/programs/`. Expected outputs are in `/app/expected/`.

Build and optimization pipeline:

    /app/mugo < /app/programs/fib.go > fib.asm
    python3 /app/optimizer.py < fib.asm > fib_opt.asm
    nasm -felf64 -o fib.o fib_opt.asm
    ld -o fib fib.o
    ./fib

Study the Mugo compiler's code generation functions (especially `genBinaryInt`, `genReturn`, `genJumpIfZero`, `genFetchInstrs`, `genAssignInstrs`) to identify the patterns that produce redundant stack operations.