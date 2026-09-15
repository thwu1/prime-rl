# ChocoPy Type System Specification

This document specifies the type system rules for ChocoPy v2.2, a statically typed dialect of
Python 3.6 designed for compiler courses. This specification is derived from the formal rules
in the ChocoPy Language Reference Manual (UC Berkeley).

## 1. Type Hierarchy

ChocoPy types form a tree rooted at `object`:

- **Class types**: `object`, `int`, `bool`, `str`, and user-defined classes.
- **List types**: `[T]` for any type `T`. Lists are parameterized: `[int]`, `[str]`, `[[int]]`, etc.
- **Special types** (cannot appear in source code):
  - `<None>` — the type of the `None` literal.
  - `<Empty>` — the type of the empty list expression `[]`.

Predefined subclass relationships:
- `int`, `bool`, `str` are direct subclasses of `object`.
- Every user-defined class has exactly one superclass (single inheritance).
- The superclass must be `object` or a previously defined user-defined class.
- The superclass may NOT be `int`, `bool`, or `str`.

## 2. Conformance (subtyping): T1 <= T2

Conformance defines the standard subtyping relation:

1. **Reflexive**: `A <= A` for all types `A`.
2. **Class subtyping**: If class `C` is a subclass of `P`, then `C <= P`.
3. **Transitive**: If `A <= C` and `C <= P`, then `A <= P`.
4. **List to object**: `[T] <= object` for any type `T`.
5. **Special types**:
   - `<None> <= <None>` and `<None> <= object` (and nothing else).
   - `<Empty> <= <Empty>` and `<Empty> <= object` (and nothing else).
6. **List types are NOT covariant**: `[T1] <= [T2]` is FALSE even if `T1 <= T2`,
   unless `T1 == T2` (reflexive case).

## 3. Assignment Compatibility: T1 <=_a T2

Assignment compatibility is a relaxation of conformance used for assignments
and function argument passing:

`T1 <=_a T2` if **any** of the following hold:

1. `T1 <= T2` (ordinary subtyping).
2. `T1` is `<None>` AND `T2` is NOT one of `{int, bool, str}`.
3. `T1` is `<Empty>` AND `T2` is a list type `[T]`.
4. `T1` is `[<None>]` AND `T2` is `[T]` AND `<None> <=_a T`.

**Key consequences:**
- `None` can be assigned to variables of type `object`, any user-defined class,
  or any list type, but NOT to `int`, `bool`, or `str`.
- The empty list `[]` (type `<Empty>`) can be assigned to any list-typed variable.
- A list of `None` values like `[None, None]` (type `[<None>]`) can be assigned
  to `[Animal]` but NOT to `[int]` (because `<None> <=_a int` is false).

## 4. Join (Least Upper Bound): T1 ⊔ T2

The join of two types is the LEAST type `C` such that `T1 <=_a C` and `T2 <=_a C`,
and for all `D` where `T1 <=_a D` and `T2 <=_a D`, we have `C <=_a D`.

**Computation rules:**
- If `T1 <=_a T2`, then `T1 ⊔ T2 = T2`.
- If `T2 <=_a T1`, then `T1 ⊔ T2 = T1`.
- Otherwise, if both are class types, `T1 ⊔ T2 = LCA(T1, T2)` in the class tree.
- Otherwise (e.g., unrelated list types), `T1 ⊔ T2 = object`.

**Examples:**
- `join(Dog, Cat) = Animal` (LCA in class tree)
- `join([int], [str]) = object` (list types are unrelated)
- `join(<None>, Animal) = Animal` (`<None> <=_a Animal`)
- `join(<Empty>, [int]) = [int]` (`<Empty> <=_a [int]`)

## 5. Expression Type Rules

### 5.1 Arithmetic and Numeric Operations
- `int + int`, `int - int`, `int * int`, `int // int`, `int % int` → `int`
- `-int` → `int`

### 5.2 Numeric Comparisons
- `int < int`, `int <= int`, `int > int`, `int >= int` → `bool`

### 5.3 Equality Comparisons
- `int == int`, `int != int` → `bool`
- `bool == bool`, `bool != bool` → `bool`
- `str == str`, `str != str` → `bool`
- Both operands MUST be the SAME type (int, bool, or str). Mixed types are errors.

### 5.4 Logical Operations
- `bool and bool`, `bool or bool` → `bool`
- `not bool` → `bool`

### 5.5 String Operations
- `str + str` → `str` (concatenation)
- `str[int]` → `str` (indexing; returns single-character string)

### 5.6 The `is` Operator
- `e1 is e2` → `bool`
- Both operands must have types that are NOT `int`, `bool`, or `str`.
- Valid operand types: `object`, user-defined classes, list types, `<None>`.

### 5.7 List Operations
- `[T1] + [T2]` → `[T1 ⊔ T2]` (list concatenation)
- `[T][int]` → `T` (list indexing)
- List element assignment `[T1][int] = e` requires the value type `<=_a T1`.

### 5.8 List Display (List Literal)
- `[]` has type `<Empty>`.
- `[e1, e2, ..., en]` has type `[T]` where `T = T1 ⊔ T2 ⊔ ... ⊔ Tn`.

### 5.9 Conditional Expression
- `e1 if e0 else e2` where `e0: bool` → type is `T1 ⊔ T2`.

### 5.10 Object Construction
- `ClassName()` → `ClassName` (the class type).

### 5.11 Attribute Access
- `e.attr` where `e: T` and `T` has attribute `attr` of type `U` → `U`.
- Attributes are inherited from superclasses.

### 5.12 Method Calls (Dynamic Dispatch)
- `e0.method(e1, ..., en)` where `e0: T`:
  - Look up `method` in class `T` or its ancestors.
  - The method has parameters `(self: T_self, p1: P1, ..., pn: Pn)` and return type `R`.
  - Each argument `ei` must satisfy `Ti <=_a Pi`.
  - The expression type is `R`.

### 5.13 Function Invocation
- `f(e1, ..., en)` where `f` has parameters `(p1: P1, ..., pn: Pn)` and return `R`:
  - Each argument must satisfy `Ti <=_a Pi`.
  - The expression type is `R`.

## 6. Method Override Rules

When a class `C` (with superclass `P`) defines method `m` that also exists in `P`
(or an ancestor of `P`), the override is valid only if:

1. The return type is **exactly the same** as the parent's method.
2. The number of parameters is **exactly the same**.
3. All parameter types **except the first** (self) are **exactly the same**.

The first parameter (self) type naturally differs (it's the defining class), which is permitted.

## 7. Object Layout (RISC-V Implementation Guide)

### 7.1 Type Tags
Fixed type tags:
- `int` → 1
- `bool` → 2
- `str` → 3
- All list types → -1

User-defined classes receive type tags starting from 4, assigned in order of definition.

### 7.2 Dispatch Tables
A class's dispatch table lists `(method_name, defining_class)` entries:
- Start with the parent class's dispatch table (copy it).
- For each method defined in the current class:
  - If it **overrides** a parent method: replace the entry at the **same index**.
  - If it is a **new** method: append at the end.

This ensures overridden methods keep their parent's slot index, enabling
polymorphic dispatch without runtime method lookup.

### 7.3 Attribute Layout
Object attributes in memory follow this order:
- Header: 3 words (type tag, size in words, dispatch table pointer).
- Parent class attributes (in their inherited order).
- Current class's new attributes (in definition order).

Object size = 3 (header) + number of attributes (including inherited).

### 7.4 Method Resolution
When resolving a method call `obj.method(args)` at runtime:
1. Read the dispatch table pointer from the object header.
2. Index into the dispatch table at the method's known slot.
3. Jump to the method address found there.

At compile time (type checking), method resolution walks up the class hierarchy
from the receiver's static type until the method is found.
