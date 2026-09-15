Implement a complete MiniPratt expression language evaluator as a C program at `/app/`. The implementation must use `flex` for tokenization — you must write a `.l` lexer specification file — and a hand-written Pratt (top-down operator precedence) parser in C.

A `Makefile` is provided at `/app/Makefile`. It expects three source files: `tokens.h` (shared token type definitions between flex and parser), `lexer.l` (flex specification), and `minipratt.c` (parser, evaluator, and driver). Running `make` in `/app/` must produce a `minipratt` binary that takes a `.mp` source file path as its sole argument and prints the integer result of the last expression to stdout.

The language includes C-like arithmetic, comparison, logical, and bitwise operators across 13 precedence levels, right-associative exponentiation (`**`), ternary conditional (`? :`), `let ... in ...` bindings with lexical scoping, recursive and mutually-recursive `fn` definitions, and user-definable infix/prefix operators (`operator infixl/infixr/prefix`) that dynamically extend the parser's operator table during parsing.

See `/app/spec.md` for the full language specification and `/app/examples/` for sample programs.