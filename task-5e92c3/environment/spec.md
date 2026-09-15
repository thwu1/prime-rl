# LLVMlite Language Specification

LLVMlite is a simplified subset of LLVM IR designed for educational compiler construction. This document specifies the complete language that your compiler must support.

## Types

| Type   | Description                     | Size    |
|--------|---------------------------------|---------|
| `i1`   | 1-bit integer (boolean)         | 1 bit   |
| `i64`  | 64-bit signed integer           | 8 bytes |
| `i64*` | Pointer to i64                  | 8 bytes |
| `void` | No value (for function returns) | N/A     |

## Operands

An operand in an instruction can be one of:

- **Register**: `%name` — a local virtual register (SSA value)
- **Immediate**: an integer literal, e.g., `42`, `-1`, `0`
- **Global**: `@name` — reference to a global variable (represents its address)

## Program Structure

A program consists of zero or more of the following top-level declarations, in any order:

### Global Variable Declaration

```
@name = global i64 <integer_value>
```

Declares a global variable initialized to the given value.

### External Function Declaration

```
declare <return_type> @name(<param_type1>, <param_type2>, ...)
```

Declares an externally-defined function (provided by the runtime).

### Function Definition

```
define <return_type> @name(<type1> %param1, <type2> %param2, ...) {
<basic_blocks>
}
```

## Basic Blocks

A function body consists of one or more basic blocks. Each block has an optional label followed by a sequence of instructions ending with a terminator (branch or return).

```
label_name:
  <instruction>
  <instruction>
  ...
  <terminator>
```

The first basic block is the function's entry point. If no label is provided for the first block, it is implicitly named `entry`.

## Instructions

### Arithmetic Operations

```
%result = add i64 <op1>, <op2>
%result = sub i64 <op1>, <op2>
%result = mul i64 <op1>, <op2>
```

Standard signed integer arithmetic. Operands can be registers or immediates.

### Bitwise Operations

```
%result = and  i64 <op1>, <op2>
%result = or   i64 <op1>, <op2>
%result = xor  i64 <op1>, <op2>
%result = shl  i64 <op1>, <op2>    ; left shift
%result = lshr i64 <op1>, <op2>    ; logical (unsigned) right shift
%result = ashr i64 <op1>, <op2>    ; arithmetic (signed) right shift
```

### Integer Comparison

```
%result = icmp <cond> i64 <op1>, <op2>
```

Produces an `i1` (boolean) result. `<cond>` is one of:

| Condition | Meaning                   |
|-----------|---------------------------|
| `eq`      | equal                     |
| `ne`      | not equal                 |
| `slt`     | signed less than          |
| `sgt`     | signed greater than       |
| `sle`     | signed less than or equal |
| `sge`     | signed greater or equal   |

### Memory Operations

**Stack allocation:**
```
%ptr = alloca i64
```
Allocates 8 bytes on the stack, returns a pointer (`i64*`) to the allocated space.

**Store:**
```
store i64 <value>, i64* <pointer>
```
Stores the 64-bit value at the address given by the pointer.

**Load:**
```
%result = load i64, i64* <pointer>
```
Loads the 64-bit value at the address given by the pointer.

### Pointer Arithmetic

```
%result = getelementptr i64, i64* <base>, i64 <index>
```

Computes `base + index * 8` (byte offset for i64 elements). Returns a pointer (`i64*`).

### Type Conversions

```
%result = zext i1 <value> to i64
```
Zero-extends a 1-bit value to 64 bits (0 stays 0, 1 stays 1).

```
%result = trunc i64 <value> to i1
```
Truncates a 64-bit value to 1 bit (keeps the least significant bit).

```
%result = bitcast <type1>* <value> to <type2>*
```
Reinterprets a pointer type. No-op at runtime.

### Control Flow (Terminators)

Every basic block must end with exactly one terminator instruction.

**Unconditional branch:**
```
br label %<target>
```

**Conditional branch:**
```
br i1 <condition>, label %<if_true>, label %<if_false>
```
Branches to `<if_true>` if condition is non-zero, `<if_false>` otherwise.

**Return:**
```
ret i64 <value>
ret void
```

### Function Calls

```
%result = call <return_type> @<function_name>(<type1> <arg1>, <type2> <arg2>, ...)
call void @<function_name>(<type1> <arg1>, ...)
```

Calls the named function with the given arguments. Arguments are passed according to the System V AMD64 ABI.

## Target Architecture

Your compiler must generate x86-64 assembly for Linux (GNU assembler syntax), following the System V AMD64 ABI calling convention:

- **Integer arguments** (in order): `%rdi`, `%rsi`, `%rdx`, `%rcx`, `%r8`, `%r9`
- **Additional arguments** (7th and beyond): pushed onto the stack right-to-left before the `call`
- **Return value**: `%rax`
- **Stack alignment**: the stack pointer (`%rsp`) must be 16-byte aligned immediately before any `call` instruction
- **Callee-saved registers**: `%rbx`, `%rbp`, `%r12`–`%r15`
- **Caller-saved registers**: all others (`%rax`, `%rcx`, `%rdx`, `%rsi`, `%rdi`, `%r8`–`%r11`)

## Runtime Functions

The C runtime (`/app/runtime.c`) provides these external functions:

- `void @ll_print_int(i64)` — prints an integer followed by a newline to stdout
- `i64* @ll_alloc_array(i64)` — allocates a zero-initialized array of the given number of i64 elements, returns pointer to first element

## Entry Point

Every program must define a function `@program` that returns `i64`. The runtime calls `program()` and uses the return value (masked to 0–255) as the process exit code.

## Comments

Lines beginning with `;` are comments. Inline comments (`;` appearing mid-line) extend to the end of that line.
