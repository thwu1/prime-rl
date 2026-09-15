The directory `/app/` contains an incomplete compiler backend that processes programs represented as control flow graphs (CFGs) of x86-64-like instructions. The compiler can represent programs with variables, physical registers, constants, branches, loops, and function calls — but it cannot yet allocate variables to physical registers or generate executable assembly.

Four Python modules need working implementations:

- `/app/liveness.py` — analyze which variables are live at each program point
- `/app/interference.py` — determine which variables cannot share the same register
- `/app/coloring.py` — assign registers (or stack spill slots) to variables
- `/app/codegen.py` — emit x86-64 assembly (AT&T syntax) that compiles with `gcc`

The data structures, instruction representation, register definitions, and driver code are already provided in `/app/cfg.py` and `/app/allocator.py`. Each stub module has a function signature and type annotations describing its inputs and outputs.

The register allocator must produce correct allocations for programs with arbitrary control flow (branches, loops, nested loops), function calls (with correct caller-save/callee-save semantics), and high register pressure (programs requiring more registers than the 12 available, necessitating stack spills).

The code generator must produce a function named `program` that follows the System V AMD64 ABI, correctly manages the stack frame and callee-save registers, respects x86-64 instruction encoding constraints, and returns its result in `%rax`. A C driver at `/app/main.c` calls `program()` and prints the result.

End-to-end verification compiles the generated assembly with `gcc -no-pie`, runs the resulting executable, and checks the output against expected values. Validate your work by running `python3 /app/test_local.py`.