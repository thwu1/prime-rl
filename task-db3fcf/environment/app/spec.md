# MiniCalc Bytecode Specification

## Language Overview

MiniCalc is a minimal imperative language with integer arithmetic, control flow,
functions, and print output. All values are integers. Variables follow AWK-like
scoping: function parameters are local; all other variables are global.

## Bytecode Format

Bytecode is stored as JSON with this structure:

```json
{
  "main": [ [opcode, arg1, ...], ... ],
  "functions": {
    "name": {
      "params": ["p1", "p2"],
      "code": [ [opcode, arg1, ...], ... ]
    }
  }
}
```

Each instruction is a JSON array. The first element is the opcode string.
Subsequent elements are arguments.

## Opcodes

### Stack Operations
- `["PUSH_INT", value]` — Push integer constant onto stack
- `["POP"]` — Discard top of stack
- `["DUP"]` — Duplicate top of stack

### Arithmetic (pop b, pop a, push result)
- `["ADD"]` — a + b
- `["SUB"]` — a - b
- `["MUL"]` — a * b
- `["DIV"]` — a / b (truncation toward zero)
- `["MOD"]` — a % b (sign follows dividend)
- `["NEG"]` — Negate top of stack (in-place)

### Comparison (pop b, pop a, push 1 or 0)
- `["EQ"]` — a == b
- `["NE"]` — a != b
- `["LT"]` — a < b
- `["LE"]` — a <= b
- `["GT"]` — a > b
- `["GE"]` — a >= b

### Logical
- `["NOT"]` — Push 1 if top is 0, else push 0 (in-place)
- `["AND"]` — Pop b, pop a, push 1 if both nonzero else 0
- `["OR"]`  — Pop b, pop a, push 1 if either nonzero else 0

### Variables
- `["LOAD", name]` — Push value of variable (local first, then global; 0 if undefined)
- `["STORE", name]` — Pop value and store (to local if name is a function param, else global)

### Control Flow
- `["JMP", target]` — Unconditional jump to instruction index
- `["JMP_FALSE", target]` — Pop value; jump if zero
- `["HALT"]` — Stop execution

### Functions
- `["CALL", func_name, nargs]` — Pop nargs arguments (topmost = last arg), invoke function
- `["RET"]` — Pop return value, restore caller state, push return value in caller

### Output
- `["PRINT", nargs]` — Pop nargs values, print space-separated with trailing newline

## Execution Semantics

- The VM maintains a single shared stack across function calls
- CALL saves (return_ip, code_ref, local_vars) on a separate call stack
- RET restores from the call stack
- Jump targets are absolute instruction indices (0-based) within the current code block
- Uninitialized variables read as 0
- Each function body and the main code block are independent code arrays
- A STORE inside a function writes to local scope if the variable name matches
  a parameter of the current function; otherwise it writes to global scope
- A LOAD inside a function checks local scope first (function params), then
  global scope; returns 0 if the variable is not found in either
