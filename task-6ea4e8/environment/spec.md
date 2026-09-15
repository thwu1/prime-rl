# TAC Language Specification

## Overview

Three-Address Code (TAC) is a simple intermediate representation used in compilers. Each instruction has at most three operands (one destination, up to two sources).

## Lexical Elements

- **Variables**: `[a-zA-Z_][a-zA-Z0-9_]*` — alphanumeric identifiers starting with a letter or underscore.
- **Constants**: Integer literals, optionally preceded by `-` for negative values (e.g., `42`, `-7`, `0`).
- **Comments**: Lines starting with `#` are ignored.
- **Blank lines**: Ignored.

## Instructions

Each non-blank, non-comment line contains exactly one instruction:

| Syntax | Semantics |
|--------|-----------|
| `x = c` | Assign constant `c` to variable `x` |
| `x = y` | Copy variable `y` into `x` |
| `x = y op z` | Binary operation: `x ← y op z` (y, z may be variables or constants) |
| `x = NEG y` | Unary negation: `x ← -y` |
| `LABEL name` | Define label `name` at this point |
| `GOTO name` | Unconditional jump to `LABEL name` |
| `IF x relop y GOTO name` | Conditional jump: if `x relop y` is true, jump to `LABEL name`; otherwise fall through. `x` and `y` may be variables or constants. |
| `PRINT x` | Output the value of `x` (variable or constant) followed by a newline |

## Operators

- **Binary arithmetic**: `+`, `-`, `*`, `/`, `%`
  - `/` is integer division (truncates toward negative infinity, Python-style `//`)
  - `%` is integer modulo (Python-style `%`)
  - Division/modulo by zero yields `0`
- **Relational** (used only in `IF`): `==`, `!=`, `<`, `>`, `<=`, `>=`

## Execution Model

- Execution begins at the first instruction and proceeds sequentially unless redirected by `GOTO` or `IF`.
- The program terminates when the program counter advances past the last instruction.
- All variables are integers. Using an undefined variable is a runtime error.
- There is a safety limit of 10,000,000 executed instructions to prevent infinite loops.

## Example

```
x = 5
y = 3
z = x + y
IF z > 7 GOTO big
PRINT z
GOTO done
LABEL big
PRINT 999
LABEL done
```

Output: `8` (since 5+3=8, and 8>7 is true, jumps to `big`, prints 999... wait, 8>7 is true so it prints 999).

Corrected: Output is `999`.

## Interpreter

Use `/app/tac_interpreter.py` to run any TAC program:

```
python3 /app/tac_interpreter.py program.tac
```
