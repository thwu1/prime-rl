Build an executable at `/app/transpile.py` that accepts a `.lox` file path as a command-line argument and writes valid Python 3 code to stdout. When the generated Python is executed, it must produce byte-for-byte identical stdout to the reference Lox interpreter at `/app/run_lox.py`. Exit with code 65 for Lox syntax errors.

## Environment

- `/app/Lox.g4` — ANTLR4 combined grammar describing the full Lox language syntax.
- `/app/Makefile` — `make generate` runs the ANTLR4 tool to produce a Python 3 lexer, parser, and visitor in `/app/gen/`. `make clean` removes generated files.
- The ANTLR4 tool jar is at `/usr/local/lib/antlr-4.13.2-complete.jar`; Java runtime (`default-jre-headless`), `make`, and `wget` are pre-installed. The ANTLR4 Python runtime (`antlr4-python3-runtime`) is **not** pre-installed — install it with `pip3`.
- `/app/lox/` and `/app/run_lox.py` — a full reference Lox tree-walk interpreter. Test against it with `python3 /app/run_lox.py run <file.lox>`.

## Constraints

You **must** use the ANTLR4 toolchain for lexing and parsing: generate the Python parser from `Lox.g4` (extend or fix the grammar if needed), then build your transpiler on top of ANTLR4's generated lexer, parser, and visitor classes. Do not use the hand-written scanner/parser in `/app/lox/` for your transpiler — those are part of the reference interpreter only.

The transpiler must handle all Lox features: number/string/boolean/nil literals, arithmetic with type checking, variable declarations and block scoping, `if`/`else`/`while`/`for`, first-class functions with closures, classes with `init` constructors, field access, `this`, single inheritance, `super` calls, `print`, and `and`/`or` logical operators with short-circuit semantics.

Key semantic gaps the generated Python must bridge:

- **Truthiness**: only `false` and `nil` are falsy; `0` and `""` are truthy.
- **Scoping**: Lox block scoping vs Python function scoping — emulate with an environment chain.
- **Number formatting**: `2` not `2.0` for whole-number floats.
- **Type-checked operators**: `+` accepts two numbers or two strings only; arithmetic rejects non-numbers.
- **Classes**: `init()` returns the instance; `super` resolves from superclass but binds to receiver.
- **Logical ops**: `and`/`or` return operand values (not booleans) with short-circuit evaluation.

The generated Python must be self-contained (standard library only, no ANTLR4 dependency at execution time).