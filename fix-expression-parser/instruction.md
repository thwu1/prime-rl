The directory `/app/` contains a CMake-based multi-file C++ expression evaluator that currently fails to build. Source files are in `src/` with headers in `include/`. The resulting binary must be at `/app/parser`.

`/app/parser` reads semicolon-delimited expressions from stdin and writes one result line per expression to stdout.

For valid expressions, output the integer result. For invalid expressions, output `ERROR <line>:<col>` (1-based position of the offending token) and continue at the next semicolon or EOF. Empty statements (bare `;`) produce no output.

**Language specification:**

- Integer literals: `42`, `0`, `100`
- Boolean literals: `true` (value 1), `false` (value 0)
- Let-bindings: `let <name> = <init> in <body>` -- the binding is visible only within `<body>`; after `<body>` completes the variable is no longer accessible
- Identifiers: `[a-zA-Z_][a-zA-Z0-9_]*`
- Binary arithmetic (left-associative): `+`, `-`, `*`, `/`, `%`
- Comparison (left-associative): `<`, `>`, `<=`, `>=`, `==`, `!=` -- return 1 or 0
- Logical (left-associative, short-circuit): `&&`, `||` -- when the left operand determines the result, the right operand is not evaluated and cannot produce errors; return 1 or 0
- Unary prefix: `-` (negation), `+` (identity), `!` (logical not: non-zero to 0, zero to 1)
- Ternary (right-associative): `cond ? then : else`
- Parentheses: `(expr)`
- Comments: `#` to end of line
- Statement separator: `;`

**Operator precedence** (highest first):

1. Unary `-`, `+`, `!`
2. `*`, `/`, `%`
3. `+`, `-`
4. `<`, `>`, `<=`, `>=`, `==`, `!=`
5. `&&`
6. `||`
7. `? :`

Division/modulo by zero is an error at the operator's position.

**Examples:**

| Input | Output |
|---|---|
| `3 * 4 + 2;` | `14` |
| `8 - 3 - 2;` | `3` |
| `let x = 5 in x + 1;` | `6` |
| `0 && 1 / 0;` | `0` |
| `5 != 3;` | `1` |
| `2 + ; 3;` | `ERROR 1:5` then `3` |

**Success criteria:**

- `/app/parser` compiles and links via the CMake build system without errors
- Expressions evaluate per the precedence, associativity, scoping, and short-circuit rules
- Let-bindings are lexically scoped
- Error recovery continues to subsequent statements
