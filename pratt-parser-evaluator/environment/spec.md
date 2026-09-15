# MiniPratt Language Specification

## Overview

MiniPratt is a small expression language with support for user-defined operators.
Programs are sequences of definitions and expressions that evaluate to integers.

## Lexical Structure

### Tokens
- **Numbers**: Sequences of digits (`0-9`). Examples: `0`, `42`, `1024`
- **Identifiers**: Start with a letter or underscore, followed by letters, digits, or underscores. Examples: `x`, `foo_bar`, `_temp`
- **Keywords**: `let`, `in`, `if`, `then`, `else`, `fn`, `operator`, `infixl`, `infixr`, `prefix`, `true`, `false`
  - `true` evaluates to `1`, `false` evaluates to `0`
- **Operators**: `+`, `-`, `*`, `/`, `%`, `**`, `==`, `!=`, `<`, `>`, `<=`, `>=`, `<<`, `>>`, `&&`, `||`, `&`, `|`, `^`, `~`, `!`, `?`, `:`
  - Multi-character operators use longest match (e.g., `**` is one token, not two `*`)
- **Punctuation**: `(`, `)`, `=`, `;`, `,`
- **Comments**: `//` to end of line

### Whitespace
Whitespace (spaces, tabs, newlines) separates tokens but is otherwise ignored.

## Program Structure

A program consists of top-level items separated by semicolons (`;`). Trailing semicolons are allowed.

Top-level items:
1. **Function definitions**: `fn name(params) = body`
2. **Operator definitions**: `operator fixity precedence name (params) = body`
3. **Expressions**: Any expression

The program's result is the value of the **last** expression evaluated. Function and operator definitions do not produce a value.

**Important**: All `fn` definitions are available globally -- functions defined later in the source can be called by functions defined earlier (mutual recursion is supported). However, `operator` definitions take effect only for the parsing of subsequent source text -- a custom operator must be defined before it is used.

## Expressions

### Atoms
- **Integer literals**: `0`, `42`, `1024`
- **Boolean literals**: `true` (= 1), `false` (= 0)
- **Variables**: Identifiers bound by `let`, function parameters, or operator parameters
- **Parenthesized expressions**: `(expr)`

### Built-in Operators

Operators listed from highest to lowest precedence (higher number = tighter binding):

| Prec | Operators | Assoc | Type |
|------|-----------|-------|------|
| 14 | `**` | right | binary |
| 13 | `-` (negation), `!` (logical not), `~` (bitwise not) | -- | prefix |
| 12 | `*`, `/`, `%` | left | binary |
| 11 | `+`, `-` (subtraction) | left | binary |
| 10 | `<<`, `>>` | left | binary |
| 9 | `<`, `<=`, `>`, `>=` | left | binary |
| 8 | `==`, `!=` | left | binary |
| 7 | `&` (bitwise and) | left | binary |
| 6 | `^` (bitwise xor) | left | binary |
| 5 | `|` (bitwise or) | left | binary |
| 4 | `&&` (logical and) | left | binary |
| 3 | `||` (logical or) | left | binary |
| 2 | `? :` (ternary) | right | ternary |

### Operator Semantics

- **Arithmetic**: `+`, `-`, `*` operate on 64-bit signed integers. `/` is integer division truncating toward zero. `%` satisfies `a == (a / b) * b + (a % b)`.
- `**` is integer exponentiation (non-negative exponents only).
- **Bitwise**: `&`, `|`, `^`, `~`, `<<`, `>>` operate on binary representations.
- **Comparison**: `<`, `<=`, `>`, `>=`, `==`, `!=` return `1` for true, `0` for false.
- **Logical**: `&&` and `||` use short-circuit evaluation. Return `1` for true, `0` for false. Any non-zero value is truthy.
- **Ternary**: `cond ? then_expr : else_expr` -- evaluates and returns `then_expr` if `cond` is non-zero, otherwise `else_expr`.
- **Unary**: `-x` negates, `!x` returns 1 if x is 0 else 0, `~x` is bitwise complement.

### Let Bindings

```
let name = value_expr in body_expr
```

Binds `name` to the result of `value_expr` within `body_expr`. Scoping is lexical.

### Conditional Expressions

```
if cond_expr then then_expr else else_expr
```

The `else` clause is mandatory. If `cond_expr` is non-zero, returns `then_expr`, otherwise `else_expr`.

### Function Calls

```
name(arg1, arg2, ...)
```

Calls the function `name` with the given arguments. The number of arguments must match the parameter count.

### Function Definitions

```
fn name(param1, param2, ...) = body_expr
```

The body may reference parameters, global functions, and global operators. Function parameters shadow outer bindings. Functions see the global scope and their own parameters (not intermediate let-bindings from calling contexts).

### Operator Definitions

```
operator infixl precedence name (left_param, right_param) = body_expr
operator infixr precedence name (left_param, right_param) = body_expr
operator prefix precedence name (operand_param) = body_expr
```

Defines a new operator with a given fixity and precedence (integer, higher = tighter). The operator `name` must be an identifier. Once defined, the operator can be used in subsequent expressions with the specified precedence and associativity.

Example:
```
operator infixr 11 cat (a, b) = a * 10 + b;
1 cat 2 cat 3
```
Result: `1 cat (2 cat 3)` = `1 cat 23` = `33` (right-associative).

## Implementation Requirements

Build a C program at `/app/` using the provided `Makefile`. The `Makefile` expects these source files:

- `tokens.h` -- shared token type definitions
- `lexer.l` -- flex lexer specification (tokenization must be performed by flex)
- `minipratt.c` -- Pratt parser, tree-walking evaluator, and driver

Run `make` in `/app/` to produce the `minipratt` binary. The binary takes a single command-line argument (a `.mp` file path) and prints the integer result of the last expression to stdout.
