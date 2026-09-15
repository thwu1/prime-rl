# Static Analyzer Specification

## Overview

Implement an abstract interpreter that analyzes programs written in a simple imperative language. The analyzer uses the **interval abstract domain** to track possible integer values of each variable, and must correctly detect three types of safety violations:

1. **Buffer Overflow (boa)**: Array access with an index outside valid bounds
2. **Division by Zero (dbz)**: Division or modulo with a divisor that could be zero
3. **Assertion Violation (assert)**: An assertion condition that could be false

## Input Format

Programs are specified as JSON files:

```json
{
  "name": "program_name",
  "vars": ["x", "y"],
  "arrays": {"a": 10, "b": 5},
  "body": [<statement>, ...]
}
```

- `vars`: Integer variable names used in the program
- `arrays`: Map from array name to its size (number of elements, 0-indexed)
- `body`: List of statements executed sequentially

### Statements

Each statement has a `"stmt"` type and a `"line"` number (used for check reporting):

| Type | Format |
|------|--------|
| assign | `{"stmt": "assign", "target": "x", "expr": <expr>, "line": N}` |
| array_write | `{"stmt": "array_write", "array": "a", "index": <expr>, "value": <expr>, "line": N}` |
| while | `{"stmt": "while", "cond": <expr>, "body": [<stmt>...], "line": N}` |
| if | `{"stmt": "if", "cond": <expr>, "then_body": [<stmt>...], "line": N}` with optional `"else_body": [<stmt>...]` |
| assert | `{"stmt": "assert", "cond": <expr>, "line": N}` |

### Expressions

Each expression has an `"expr"` type:

| Type | Format | Semantics |
|------|--------|-----------|
| const | `{"expr": "const", "value": N}` | Integer literal |
| var | `{"expr": "var", "name": "x"}` | Variable read |
| nondet | `{"expr": "nondet"}` | Non-deterministic integer (any value) |
| array_read | `{"expr": "array_read", "array": "a", "index": <expr>}` | Array element read |
| binop | `{"expr": "binop", "op": "<op>", "left": <expr>, "right": <expr>}` | Binary operation |
| unop | `{"expr": "unop", "op": "<op>", "operand": <expr>}` | Unary operation |

Binary operators: `+`, `-`, `*`, `/`, `%`, `==`, `!=`, `<`, `<=`, `>`, `>=`

Unary operators: `-` (negation), `!` (logical not)

Comparison operators return 1 (true) or 0 (false). Conditions in `while`, `if`, and `assert` treat 0 as false and non-zero as true.

## Analysis Requirements

### Interval Abstract Domain

Each variable maps to an interval [lo, hi] representing all possible integer values. Use mathematical integers (no overflow). A `nondet` expression yields [-infinity, +infinity].

**Domain operations** (given I1 = [a, b] and I2 = [c, d]):

| Operation | Definition |
|-----------|-----------|
| Join (least upper bound) | I1 join I2 = [min(a,c), max(b,d)] |
| Meet (greatest lower bound) | I1 meet I2 = [max(a,c), min(b,d)], bottom if empty |
| Widen | I1 widen I2 = [c < a ? -inf : a, d > b ? +inf : b] |
| Narrow | I1 narrow I2 = [a == -inf ? c : a, b == +inf ? d : b] |

Bottom (empty interval) represents unreachable states:
- I join bottom = I
- bottom join I = I
- I widen bottom = I
- bottom widen I = I

### Loop Analysis

Analyze loops using fixpoint iteration:
1. **Widening phase**: Iterate applying widening at the loop head until the abstract state stabilizes. This guarantees termination.
2. **Narrowing phase**: Starting from the widened fixpoint, iterate applying narrowing to recover precision lost during widening.

The loop head equation is: X = init_state join body_transfer(filter(X, condition))

After convergence, the exit state is obtained by filtering the fixpoint with the negated loop condition.

### Conditional Branches

When entering a branch guarded by a condition, **refine** the abstract state. For `x < C`, constrain x's upper bound to C-1. For `x >= C`, constrain x's lower bound to C. Apply analogous refinements for other comparison operators. For `if-else`, analyze both branches with appropriately refined states and join the results.

### Array Contents

Array element values are NOT tracked. Every `array_read` returns [-infinity, +infinity]. Only index bounds are checked.

## Checks

Automatically emit checks at:

1. **boa**: Every `array_write` and `array_read` — is the index within [0, size-1]?
2. **dbz**: Every `/` and `%` operation — does the divisor include zero?
3. **assert**: Every `assert` statement — could the condition be false?

### Check Statuses

| Status | Meaning |
|--------|---------|
| **safe** | Property holds for ALL possible executions reaching this point. Unreachable points (bottom state) are vacuously safe. |
| **error** | Property is violated for ALL possible executions reaching this point. |
| **warning** | Cannot determine — some executions may violate, others may not. |

**boa specifics**: safe if index_interval is subset of [0, size-1]; error if index_interval and [0, size-1] are disjoint; warning otherwise.

**dbz specifics**: safe if 0 is not in divisor_interval; error if divisor_interval equals {0}; warning otherwise.

**assert specifics**: safe if filtering by the negated condition yields bottom (no violation possible); error if filtering by the condition yields bottom (no satisfaction possible); warning otherwise.

## Output Format

Print a JSON object to stdout:

```json
{
  "checks": [
    {"line": 3, "kind": "boa", "status": "safe"},
    {"line": 7, "kind": "dbz", "status": "warning"}
  ]
}
```

Checks sorted by line number, then alphabetically by kind.

## Usage

```
python3 /app/analyzer.py <program.json>
```
