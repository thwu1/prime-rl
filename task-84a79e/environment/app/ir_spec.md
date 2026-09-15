# Three-Address Code IR Specification

## Program Structure

A program consists of one or more function definitions. Execution begins at `main()`.

```
FUNC name(param1, param2, ...):
  LABEL label_name:
    instruction
    ...
  LABEL another_label:
    instruction
    ...
ENDFUNC
```

Functions with no parameters use empty parentheses: `FUNC main():`.

## Lexical Elements

- **Variable names**: `[a-z][a-z0-9_]*`
- **Function names**: `[a-z][a-z0-9_]*`
- **Label names**: `[a-z][a-z0-9_]*`
- **Integer literals**: `-?[0-9]+` (signed 64-bit)
- **Comments**: Lines where the first non-whitespace character is `#`
- **Whitespace**: Leading and trailing whitespace on each line is ignored.
  Binary operations require at least one space on each side of the operator.

## Operands

An *operand* is either a variable name or an integer literal.

## Instructions

Each instruction occupies exactly one line (blank lines and comment lines are skipped):

| Syntax | Description |
|---|---|
| `x = <operand>` | Assignment: constant load or variable copy |
| `x = <operand> <op> <operand>` | Binary operation, result stored in `x` |
| `x = CALL f(<operand>, ...)` | Call function `f`, store return value in `x` |
| `IF <operand> GOTO label` | Branch to `label` if operand is nonzero |
| `GOTO label` | Unconditional jump |
| `RETURN <operand>` | Return a value from the current function |
| `PRINT <operand>` | Print the operand's integer value followed by `\n` |

## Binary Operators

`+`  `-`  `*`  `/`  `%`  `==`  `!=`  `<`  `>`  `<=`  `>=`

- All arithmetic operates on signed 64-bit integers.
- `/` is integer division **truncated toward zero** (C semantics).
- `%` satisfies `a == (a / b) * b + a % b` (C semantics).
- Comparison operators yield `1` (true) or `0` (false).

## Control Flow

- Execution within a function proceeds top-to-bottom through instructions.
- `GOTO` and `IF ... GOTO` transfer control to the first instruction after the named `LABEL`.
- Falling off the last instruction of a `LABEL` block continues to the next `LABEL`'s first instruction.
- The first `LABEL` in a function is the entry point.

## Function Calls

- `CALL f(a1, a2, ...)` invokes `f` with the listed arguments (evaluated left-to-right).
- Parameters in the callee bind positionally to the argument values.
- Each function has its own independent variable scope (no global variables).
- `RETURN x` passes the value of `x` back to the caller.

## Default Values

- Every variable is implicitly initialized to `0` before any explicit assignment.

## Program Output

The program's observable output is the concatenation of all `PRINT` values (each followed by a newline) produced during execution of `main()`.
