# Language Semantics

## Overview

The language defined in `/app/lang.py` is a lambda calculus in Administrative Normal Form (ANF). Programs are S-expressions parsed by `lang.parse()` into an AST. Each `lambda` node is assigned a unique integer label during parsing (see `Lam.label`), starting from 1 in declaration order.

## Constructs

### Literals
- Integers: `42`, `-3`
- Booleans: `#t` (true), `#f` (false)

### Variables
Variables are lexically scoped. A variable reference evaluates to the value currently bound to that variable.

### Lambda Abstraction
`(lambda (params...) body)` creates a function that captures all variable bindings visible at the point of definition (a closure). When invoked, the body executes in the captured environment extended with parameter bindings.

### Application
`(f arg1 arg2 ...)` evaluates the function and all arguments to values, then invokes the function with the argument values. The function body executes in the closure's captured environment, extended with parameter-to-argument bindings.

### Let
`(let ((x expr)) body)` evaluates `expr`, binds the result to `x`, then evaluates `body` in the extended scope. Only single-binding `let` is supported.

### Letrec
`(letrec ((v1 e1) ... (vn en)) body)` establishes mutually recursive bindings. All variables `v1..vn` are in scope for all right-hand sides `e1..en`, enabling mutual recursion. All `ei` should be lambda expressions. Each `ei` is evaluated in the environment containing all the `vi` bindings.

### Conditionals
`(if cond then else)` evaluates `cond`. If the result is anything other than `#f` (boolean false), evaluates `then`; otherwise evaluates `else`. Only `#f` is falsy — `0`, void, and all other values are truthy.

### Mutation
`(set! var expr)` evaluates `expr` and updates the binding of `var` to the new value. This mutation is visible to all closures that share this binding (i.e., closures that captured the same variable). The expression itself evaluates to a void value.

### First-Class Continuations
`(call/cc f)` captures the current continuation — the entire pending computation from this point forward — as a callable value, then invokes `f` with this continuation as its sole argument.

- If `f` returns normally (without invoking the continuation), its return value becomes the result of the `call/cc` expression.
- If `f` invokes the captured continuation with a value `v`, computation immediately jumps back to the point of the `call/cc` expression with `v` as the result. The current computation inside `f` is abandoned (non-local escape).

### Primitives
- `(+ a b)` — integer addition
- `(- a b)` — integer subtraction
- `(* a b)` — integer multiplication
- `(= a b)` — boolean equality test
- `(< a b)` — boolean less-than test

Arguments to primitives must be atomic expressions (variables, literals, or other primitives).

## Static Analysis Specification

The analysis computes, for each variable in the program, the set of lambda labels (integers from `Lam.label`) that could be bound to that variable during any possible execution of the program.

**Soundness:** If a lambda with label `L` could be bound to variable `v` during any execution, then `L` must appear in `analyze(text)['v']`. Over-approximation is acceptable; under-approximation is not.

**Context-insensitivity:** The analysis maintains a single summary per function — it does not distinguish different call sites. When a function is called from multiple sites with different lambda arguments, all arguments are merged into the parameter's result set.

**Tracking scope:** Only lambda values are tracked (by label). Primitive values (integers, booleans) are not included in flow sets.

## Required API

### `/app/interp.py`
```python
def run(text: str):
    """Parse and evaluate the program. Return int for integers, bool for booleans."""
```

### `/app/analysis.py`
```python
def analyze(text: str) -> dict[str, set[int]]:
    """Return mapping from variable names to sets of lambda labels."""
```
