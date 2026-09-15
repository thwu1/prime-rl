# ChocoPy v2.2 Type System Reference

ChocoPy is a statically typed dialect of Python 3.6 designed for compiler courses.
This document summarizes the type rules needed to implement a ChocoPy type checker.

## 1. Types

**Primitive types:** `int`, `bool`, `str`
**Special types:** `<None>` (type of `None`), `<Empty>` (type of `[]`)
**Class types:** `object`, any user-defined class name
**List types:** `[T]` for any type T
**Function types:** `(T1, ..., Tn) -> T0` (not first-class in ChocoPy)

## 2. Type Hierarchy

All classes form a tree rooted at `object`:
- `int`, `bool`, `str` are direct subclasses of `object`
- User-defined classes inherit from `object` or another user-defined class
- `int`, `bool`, `str` **cannot** be subclassed
- `<None>` and `<Empty>` conform to `object` but are otherwise unrelated
- `[T]` conforms to `object` for any T
- List types are **not** related to each other (no covariance)

## 3. Conformance (≤)

`T1 ≤ T2` (T1 conforms to T2) iff:
- `A ≤ A` for all types A (reflexive)
- If class C is a subclass of P, then `C ≤ P`
- Transitivity: if `A ≤ C` and `C ≤ P`, then `A ≤ P`
- `<None> ≤ object`, `<Empty> ≤ object`, `[T] ≤ object`
- `int ≤ object`, `bool ≤ object`, `str ≤ object`

Note: `bool` is NOT a subclass of `int` in ChocoPy (unlike Python).

## 4. Assignment Compatibility (≤a)

`T1 ≤a T2` iff at least one of:
1. `T1 ≤ T2`
2. `T1` is `<None>` and `T2` is not `int`, `bool`, or `str`
3. `T2` is a list type `[T']` and `T1` is `<Empty>`
4. `T2` is a list type `[T']` and `T1` is `[<None>]`, where `<None> ≤a T'`

## 5. Join (⊔) — Least Upper Bound

`C = A ⊔ B` is the least type such that `A ≤a C` and `B ≤a C`.
- If `A ≤a B`, then `A ⊔ B = B`
- If `B ≤a A`, then `A ⊔ B = A`
- Otherwise, `A ⊔ B` is the least common ancestor of A and B in the class hierarchy

## 6. Variable Declarations

```
id : type = literal
```
The literal's type must be assignment-compatible with the declared type.

## 7. Assignments

```
id = expr          →  type(expr) ≤a type(id)
expr.attr = expr   →  type(RHS) ≤a type(attr)
expr[expr] = expr  →  type(RHS) ≤a element_type(LHS)
```

**Multiple assignment** `e1 = e2 = ... = en = e0`:
- Each individual assignment must type-check
- Additionally, `type(e0)` must NOT be `[<None>]`

## 8. Expressions

**Arithmetic** (`+`, `-`, `*`, `//`, `%`): both operands must be `int`, result is `int`
**String concatenation** (`+`): both operands `str`, result is `str`
**List concatenation** (`+`): `[T1] + [T2]` produces `[T1 ⊔ T2]`
**Unary minus** (`-e`): operand must be `int`, result is `int`
**Logical** (`and`, `or`, `not`): operands must be `bool`, result is `bool`
**Numerical comparisons** (`<`, `<=`, `>`, `>=`): both operands `int`, result is `bool`
**Equality** (`==`, `!=`): both operands same type from {`int`, `bool`, `str`}, result is `bool`
**Identity** (`is`): both operand types must NOT be `int`, `str`, or `bool`; result is `bool`
**Conditional** (`e1 if e0 else e2`): `e0` must be `bool`, result type is `type(e1) ⊔ type(e2)`
**Indexing** (`e1[e2]`): `e2` must be `int`; if `e1` is `str` → `str`; if `e1` is `[T]` → `T`
**List display** (`[e1, ..., en]`): type is `[T1 ⊔ ... ⊔ Tn]`; empty `[]` has type `<Empty>`

## 9. Function Calls

```
f(e1, ..., en)
```
- Number of arguments must match number of parameters
- Each `type(ei) ≤a param_type_i`
- Result type is the function's declared return type

## 10. Method Dispatch

```
e0.m(e1, ..., en)
```
- `e0` must have a class type T0
- Method m must exist in T0 (including inherited methods)
- `type(e0) ≤a self_param_type` (implicit first argument)
- Arguments checked as for function calls (excluding self)
- Result type is method's return type

## 11. Class Definitions

- Superclass must exist and must NOT be `int`, `bool`, or `str`
- Class names cannot be reused
- Attributes cannot be redefined (neither in same class nor overriding inherited)
- Methods can override inherited methods ONLY IF:
  - Return type is exactly the same
  - All parameter types except the first (self) are exactly the same

## 12. Function Definitions

- `global x`: binds `x` to the global variable (bypasses enclosing scope)
- `nonlocal x`: binds `x` to the nearest enclosing scope variable (not global)
- Variables from enclosing scope are inherited as read-only unless declared `nonlocal`
- If return type is `int`, `str`, or `bool`, all execution paths must have a `return` with non-None value
- Functions without explicit return implicitly return `None`

## 13. Control Flow

**If/elif/else**: condition must be `bool`
**While**: condition must be `bool`
**For loop** `for id in e: body`:
- If `e` has type `[T]`, then `T ≤a type(id)`
- If `e` has type `str`, then `str ≤a type(id)`
- The loop variable must be previously declared

## 14. Built-in Functions

- `print(arg: object) -> <None>`: prints int, bool, or str values
- `input() -> str`: reads a line from stdin
- `len(arg: object) -> int`: returns length of str or list

## 15. Built-in Classes

- `object`: root class, has `__init__(self: object) -> <None>`
- `int`: subclass of object, `int()` produces 0
- `bool`: subclass of object, `bool()` produces False
- `str`: subclass of object, `str()` produces ""
