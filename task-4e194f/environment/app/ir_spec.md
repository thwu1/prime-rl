# IR Language Specification

## Overview

This IR (intermediate representation) is a register-based three-address code
organised into basic blocks within functions. All values are arbitrary-precision
integers.

## Program structure

```
func <name>(<param1>, <param2>, ...):
  .<label>:
    <instruction>
    ...
  .<label>:
    ...
```

A program consists of one or more function definitions.  Each function has a
name, zero or more parameters, and one or more labelled basic blocks.
Execution begins at function `main` (no arguments) in its first block.

## Instructions

### Constants and copies

| Syntax | Semantics |
|---|---|
| `dest = const <int>` | Load integer constant |
| `dest = copy <src>` | Copy register value |

### Arithmetic / logic (binary)

| Syntax | Semantics |
|---|---|
| `dest = add a b` | `dest = a + b` |
| `dest = sub a b` | `dest = a - b` |
| `dest = mul a b` | `dest = a * b` |
| `dest = div a b` | `dest = a // b` (integer, truncate toward zero; 0 if `b==0`) |
| `dest = mod a b` | `dest = a % b` (0 if `b==0`) |

### Comparisons (binary, result 0 or 1)

| Syntax | Semantics |
|---|---|
| `dest = lt a b` | `1` if `a < b` else `0` |
| `dest = gt a b` | `1` if `a > b` else `0` |
| `dest = le a b` | `1` if `a <= b` else `0` |
| `dest = ge a b` | `1` if `a >= b` else `0` |
| `dest = eq a b` | `1` if `a == b` else `0` |
| `dest = ne a b` | `1` if `a != b` else `0` |

### Logical (binary)

| Syntax | Semantics |
|---|---|
| `dest = and a b` | `1` if both truthy else `0` |
| `dest = or  a b` | `1` if either truthy else `0` |

### Unary

| Syntax | Semantics |
|---|---|
| `dest = not a` | `1` if `a == 0` else `0` |
| `dest = neg a` | `dest = -a` |

### Control flow

| Syntax | Semantics |
|---|---|
| `br .label` | Unconditional jump |
| `cbr cond .true .false` | Branch: if `cond != 0` jump to `.true`, else `.false` |
| `ret val` | Return `val` from the current function |

### Side effects

| Syntax | Semantics |
|---|---|
| `print val` | Print integer `val` to stdout (one line) |

### Function calls

| Syntax | Semantics |
|---|---|
| `dest = call func arg1 arg2 ...` | Call `func` with arguments, store return value |

### Miscellaneous

| Syntax | Semantics |
|---|---|
| `nop` | No operation |

## Operand rules

* Binary/unary operands, `print`, `ret`, and `cbr` condition may be either a
  register name or an integer literal.
* Branch targets (`.label`) always start with a dot in source but are stored
  without the dot internally.
* Comments begin with `#` and extend to end of line.
