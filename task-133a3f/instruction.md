Implement a complete interpreter for the SysY programming language (a C subset used in Chinese national compiler design competitions).

The SysY language specification is at `/app/spec/sysy_spec.md` and the runtime library specification is at `/app/spec/sylib_spec.md`.

Create an executable at `/app/sysy_run` that takes a `.sy` source file path as its sole argument, interprets the program, writes output to stdout, and exits with the return value of `main()` (masked to 0-255).

Test programs are at `/app/programs/`, input data at `/app/inputs/`, and expected outputs at `/app/expected/`.

Your interpreter must correctly handle:
- Lexical analysis including decimal, octal (`077`), and hexadecimal (`0xFF`) integer literals
- Recursive-descent parsing with correct operator precedence per the EBNF grammar
- Nested block scoping with variable shadowing
- Short-circuit evaluation of `&&` and `||` (right operand must not be evaluated when result is determined by left operand alone)
- Multi-dimensional arrays with row-major layout
- Partial array initialization (unspecified elements default to 0)
- Compile-time constant expressions used in array dimensions and `const` declarations
- `break` and `continue` within nested `while` loops
- The runtime I/O functions: `getint`, `putint`, `putch`