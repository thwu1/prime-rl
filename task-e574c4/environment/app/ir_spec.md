# Three-Address Code (TAC) Intermediate Representation

## Program Structure

A TAC program consists of one or more function definitions. Execution begins at `main()`.

```
FUNC name(param1, param2, ...):
  label1:
    instruction
    instruction
    ...
  label2:
    instruction
    ...
END
```

## Labels

Each basic block begins with a label line: an identifier followed by a colon. Labels must be unique within a function. The first label in a function is the entry point.

## Instructions

All instructions appear inside labeled blocks, indented with whitespace.

| Form | Description |
|------|-------------|
| `var = literal` | Assign integer literal |
| `var = var2` | Copy assignment |
| `var = a OP b` | Binary operation |
| `var = OP a` | Unary operation |
| `var = CALL func(a, b, ...)` | Function call |
| `PRINT var` | Print value followed by newline |
| `IF var GOTO L1 ELSE GOTO L2` | Conditional branch |
| `GOTO label` | Unconditional jump |
| `RETURN var` | Return from function |
| `NOP` | No operation |

## Operators

- **Binary**: `+`, `-`, `*`, `/` (integer division), `%` (modulo), `==`, `!=`, `<`, `>`, `<=`, `>=`, `&&`, `||`
- **Unary**: `-` (negate), `!` (logical not)

## Values

All values are integers. Boolean results use 1 (true) and 0 (false). Division by zero returns 0.

## Control Flow

- Execution proceeds sequentially within a block until a branch, goto, or return.
- If a block has no terminating instruction (branch/goto/return), execution falls through to the next block in textual order.
- Conditional branches: if the condition variable is nonzero, jump to the true label; otherwise jump to the false label.

## Comments

Lines starting with `#` are comments and are ignored.
