# VM Instruction Set Specification

## Overview

The VM is a stack-based virtual machine that executes programs written in a
simple assembly language. Programs consist of instructions, one per line.
Blank lines and lines starting with `#` are comments and ignored.

## Execution Model

- The VM maintains a value stack, a set of named variables, and a program counter (PC).
- Values are either 64-bit signed integers or strings.
- Execution begins at the first instruction and proceeds sequentially unless
  modified by jump instructions.
- Execution terminates when `HALT` is reached or the program counter passes the
  last instruction.

## Instructions

### Stack Operations

| Instruction      | Description                         |
|------------------|-------------------------------------|
| `PUSH_INT <n>`   | Push integer `n` onto the stack     |
| `PUSH_STR <s>`   | Push string `s` onto the stack (single word, unquoted) |
| `DUP`            | Duplicate the top of the stack      |
| `DROP`           | Discard the top of the stack        |
| `SWAP`           | Swap the top two stack values       |

### Variable Operations

| Instruction    | Description                                          |
|----------------|------------------------------------------------------|
| `LOAD <var>`   | Push the value of variable `var` onto the stack       |
| `STORE <var>`  | Pop the top value and store it in variable `var`      |

### Arithmetic

Binary operations pop two values; the first value pushed is the left operand.

| Instruction | Description                                      |
|-------------|--------------------------------------------------|
| `ADD`       | Addition                                         |
| `SUB`       | Subtraction                                      |
| `MUL`       | Multiplication                                   |
| `DIV`       | Integer division (truncates toward zero)          |
| `MOD`       | Modulo                                           |
| `NEG`       | Negate top of stack (unary, pops one, pushes one) |

### Comparison

Pop two values, push `1` if the comparison is true, `0` otherwise.
First pushed value is the left operand.

| Instruction | Description        |
|-------------|--------------------|
| `CMP_EQ`    | Equal              |
| `CMP_NE`    | Not equal          |
| `CMP_LT`    | Less than          |
| `CMP_LE`    | Less than or equal |
| `CMP_GT`    | Greater than       |
| `CMP_GE`    | Greater than or equal |

### Boolean

| Instruction | Description                               |
|-------------|-------------------------------------------|
| `NOT`       | Pop value; push `1` if zero, `0` otherwise |

### Control Flow

| Instruction          | Description                              |
|----------------------|------------------------------------------|
| `LABEL <name>`       | Declare a jump target (not executed)     |
| `JUMP <label>`       | Unconditional jump to label              |
| `JUMP_TRUE <label>`  | Pop value; jump if non-zero              |
| `JUMP_FALSE <label>` | Pop value; jump if zero                  |
| `HALT`               | Terminate execution                      |

### I/O

| Instruction | Description                                |
|-------------|--------------------------------------------|
| `READ_INT`  | Read an integer from stdin and push it     |
| `PRINT`     | Pop and print value (no newline)           |
| `PRINTLN`   | Pop and print value with newline           |

## Operand Order

For binary operations (`ADD`, `SUB`, `MUL`, `DIV`, `MOD`, `CMP_*`), the
**first** value pushed is the **left** operand:

```
PUSH_INT 10
PUSH_INT 3
SUB
```

computes `10 - 3 = 7`.

## Static Instruction Count

The **static instruction count** of a program is the number of non-blank,
non-comment, non-`LABEL` lines. `LABEL` declarations, blank lines, and lines
starting with `#` are excluded from the count.
