# SysY Language Semantic Rules

## Program Structure

- A SysY program is a single file corresponding to `CompUnit`.
- There must be exactly one function named `main` with no parameters and return type `int`.
- Top-level declarations and function definitions share a single namespace: no two top-level identifiers may have the same name.
- The scope of a top-level declaration extends from its definition to the end of the file.

## Types

- The only base type is `int` (32-bit signed integer).
- Arrays can be multi-dimensional: `int a[3][4]` declares a 3x4 array.
- Functions can return `int` or `void`.

## Constants

- Constants declared with `const` must be initialized with expressions evaluable at compile time.
- Constants may be scalars or arrays.
- SysY constants are conceptually similar to C++ `constexpr`.

## Variables

### Scalars
- Uninitialized global variables are implicitly initialized to 0.
- Uninitialized local variables have undefined (indeterminate) values.

### Arrays
- Array dimensions must be constant expressions evaluating to non-negative integers.
- Arrays are stored in row-major order (C-style).

### Array Initialization (Brace Elision)
This is the trickiest part of SysY. Given `int a[D1][D2]...[Dn] = init`:

1. `{}` (empty braces): all elements initialized to 0.
2. Fully-braced form: `{{...}, {...}, ...}` where each sub-list matches the corresponding sub-array dimension.
3. Flat form: `{v1, v2, v3, ...}` fills elements in row-major order.
4. Mixed form (brace elision): When an element in an initializer list is:
   - A brace-enclosed list `{...}`: it initializes one complete sub-array at the current position. Elements not specified are zero-filled.
   - A scalar value: it fills elements sequentially within the current sub-array.
   
   Example for `int a[4][2]`:
   - `{1, 2, {3}, {5}, 7, 8}` → `{{1,2}, {3,0}, {5,0}, {7,8}}`
   - `{{1}, {3, 4}, {5}}` → `{{1,0}, {3,4}, {5,0}}`
   - `{1, 2, 3, 4, 5, 6, 7, 8}` → `{{1,2}, {3,4}, {5,6}, {7,8}}`

5. Elements not covered by the initializer are implicitly 0.

## Scoping

- Blocks (`{ ... }`) create new scopes.
- A variable declared in an inner scope shadows any same-named variable in outer scopes.
- The shadowed variable is restored when the inner scope exits.
- Variable names may coincide with function names.
- Global and local variable scopes can overlap; local takes precedence in the overlap region.

## Functions

- `int` functions should return a value via `return expr;` on all paths. If a path lacks a return statement, the return value is undefined.
- `void` functions may only use `return;` (without a value).
- Functions are defined at the top level only (no nested function definitions).
- A function's scope begins at its definition; only functions defined earlier can be called (no forward declarations).

### Parameters
- Scalar parameters (`int x`): passed by value.
- Array parameters (`int a[]`, `int a[][N]`): passed by reference. The first dimension is unspecified; subsequent dimensions must be constant expressions. The function receives a reference to the caller's array storage, so modifications are visible to the caller.
- A sub-array can be passed where a lower-dimensional array is expected: e.g., for `int mat[3][4]`, `mat[1]` can be passed to a function expecting `int arr[]`.

## Expressions

- All expressions evaluate to `int`.
- Operator precedence (high to low): unary(`+`,`-`,`!`), mul(`*`,`/`,`%`), add(`+`,`-`), rel(`<`,`>`,`<=`,`>=`), eq(`==`,`!=`), land(`&&`), lor(`||`).
- All binary operators are left-associative.
- Integer division truncates toward zero (C-style): `-7 / 2 == -3`, `-7 % 2 == -1`.
- Logical `&&` and `||` use short-circuit evaluation:
  - `a && b`: if `a` is 0, `b` is NOT evaluated; result is 0.
  - `a || b`: if `a` is non-zero, `b` is NOT evaluated; result is 1.
  - When both operands are evaluated: `&&` yields 1 if both non-zero, else 0; `||` yields 1 if either non-zero, else 0.
- `!` (logical not): `!0` is 1, `!nonzero` is 0.
- In conditional contexts (`if`, `while`): 0 is false, non-zero is true.

## Control Flow

- `if (cond) stmt [else stmt]`: dangling-else binds to nearest `if`.
- `while (cond) stmt`: standard loop.
- `break`: exits the innermost enclosing `while` loop.
- `continue`: jumps to the condition check of the innermost enclosing `while` loop.
- `return [expr];`: returns from the current function.

## Integer Literals

- Decimal: nonzero digit followed by digits (e.g., `42`, `1`).
- Octal: leading `0` followed by octal digits (e.g., `012` = 10, `0` = 0).
- Hexadecimal: `0x` or `0X` followed by hex digits (e.g., `0xFF` = 255).
- Range: [0, 2^31 - 1]. No negative literals; use unary minus.

## Comments

- Single-line: `//` to end of line.
- Multi-line: `/* ... */` (not nested).
