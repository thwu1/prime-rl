# Equality Saturation Optimizer Specification

## Expression Language

Expressions are S-expressions with the following grammar:

```
expr ::= integer                    -- integer constant (e.g., 0, 1, 42)
       | variable                   -- variable name (lowercase alphabetic, e.g., x, y, a, b)
       | '(' op expr expr ')'      -- binary operation

op   ::= '+' | '*' | '<<'
```

All operations are binary. Variables are lowercase alphabetic strings. Integer constants are non-negative.

## Cost Model

Each node has a cost. Total expression cost is the sum of all node costs:

| Node Type | Cost |
|-----------|------|
| Variable  |    1 |
| Constant  |    1 |
| `+`       |    3 |
| `*`       |    6 |
| `<<`      |    2 |

Example: `(* x 8)` has cost 6 + 1 + 1 = 8. `(<< x 3)` has cost 2 + 1 + 1 = 4.

## Rewrite Rules

The optimizer applies the following rewrite rules via equality saturation over an e-graph. Each rule asserts an equality: when the left-hand side pattern is matched in the e-graph, the right-hand side is added to the same equivalence class. Pattern variables (prefixed with `?`) match any sub-expression; the same variable appearing multiple times in a single rule must match the same equivalence class.

### Commutativity
```
(+ ?a ?b) => (+ ?b ?a)
(* ?a ?b) => (* ?b ?a)
```

### Associativity
```
(+ (+ ?a ?b) ?c) => (+ ?a (+ ?b ?c))
(+ ?a (+ ?b ?c)) => (+ (+ ?a ?b) ?c)
(* (* ?a ?b) ?c) => (* ?a (* ?b ?c))
(* ?a (* ?b ?c)) => (* (* ?a ?b) ?c)
```

### Factoring (reverse distributivity)
```
(+ (* ?a ?b) (* ?a ?c)) => (* ?a (+ ?b ?c))
```

### Identity
```
(+ ?a 0) => ?a
(* ?a 1) => ?a
```

### Zero
```
(* ?a 0) => 0
```

### Double
```
(+ ?a ?a) => (* ?a 2)
```

### Strength Reduction
```
(* ?a 2)  => (<< ?a 1)
(* ?a 4)  => (<< ?a 2)
(* ?a 8)  => (<< ?a 3)
(* ?a 16) => (<< ?a 4)
(* ?a 32) => (<< ?a 5)
```

### Constant Folding
When both children of `+` or `*` are integer constants, replace with their computed value:
```
(+ c1 c2) => c1+c2    (when c1, c2 are integer constants)
(* c1 c2) => c1*c2    (when c1, c2 are integer constants)
```

## Semantics

- `(+ a b)` = a + b (integer addition)
- `(* a b)` = a * b (integer multiplication)
- `(<< a b)` = a << b (left bit shift, equivalent to a * 2^b for non-negative b)
- All variables take positive integer values
