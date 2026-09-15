# Context-Sensitive Interprocedural Sign Analysis Specification

## Language Grammar

```
program     ::= function_def*
function_def::= "function" IDENT "(" param_list ")" "{" stmt* "}"
param_list  ::= ε | IDENT ("," IDENT)*
stmt        ::= IDENT ":=" expr ";"
              | IDENT ":=" IDENT "(" arg_list ")" ";"
              | "if" "(" cond ")" "{" stmt* "}" "else" "{" stmt* "}"
              | "while" "(" cond ")" "{" stmt* "}"
              | "return" expr ";"
expr        ::= term (("+"|"-") term)*
term        ::= factor ("*" factor)*
factor      ::= INT | IDENT | "(" expr ")"
cond        ::= expr ("<"|">"|"=="|"!="|"<="|">=") expr
arg_list    ::= ε | expr ("," expr)*
INT         ::= [0-9]+
IDENT       ::= [a-zA-Z_][a-zA-Z0-9_]*
```

Operator precedence: `*` binds tighter than `+` and `-`. All binary operators are left-associative.
Comments are not used in the test programs.

## Sign Lattice

The abstract domain is a five-element lattice with the following Hasse diagram:

```
        top
      / | \
   neg zero pos
      \ | /
       bottom
```

- `bottom` represents no possible values (unreachable).
- `neg` represents strictly negative integers.
- `zero` represents exactly zero.
- `pos` represents strictly positive integers.
- `top` represents any integer (unknown sign).

### Join (least upper bound)

| ⊔      | bottom | neg | zero | pos | top |
|--------|--------|-----|------|-----|-----|
| bottom | bottom | neg | zero | pos | top |
| neg    | neg    | neg | top  | top | top |
| zero   | zero   | top | zero | top | top |
| pos    | pos    | top | top  | pos | top |
| top    | top    | top | top  | top | top |

### Meet (greatest lower bound)

| ⊓      | bottom | neg    | zero   | pos    | top  |
|--------|--------|--------|--------|--------|------|
| bottom | bottom | bottom | bottom | bottom | bottom |
| neg    | bottom | neg    | bottom | bottom | neg  |
| zero   | bottom | bottom | zero   | bottom | zero |
| pos    | bottom | bottom | bottom | pos    | pos  |
| top    | bottom | neg    | zero   | pos    | top  |

## Abstract Transfer Functions

### Constants

- A non-negative integer literal `n`: if `n > 0` then `pos`, if `n == 0` then `zero`.

### Addition

| +      | bottom | neg | zero | pos | top |
|--------|--------|-----|------|-----|-----|
| bottom | bottom | bottom | bottom | bottom | bottom |
| neg    | bottom | neg | neg  | top | top |
| zero   | bottom | neg | zero | pos | top |
| pos    | bottom | top | pos  | pos | top |
| top    | bottom | top | top  | top | top |

### Negation (unary minus, used to define subtraction)

| negate(x) | result |
|-----------|--------|
| bottom    | bottom |
| neg       | pos    |
| zero      | zero   |
| pos       | neg    |
| top       | top    |

### Subtraction

`a - b = a + negate(b)`

### Multiplication

| *      | bottom | neg  | zero | pos  | top  |
|--------|--------|------|------|------|------|
| bottom | bottom | bottom | bottom | bottom | bottom |
| neg    | bottom | pos  | zero | neg  | top  |
| zero   | bottom | zero | zero | zero | zero |
| pos    | bottom | neg  | zero | pos  | top  |
| top    | bottom | top  | zero | top  | top  |

Note: `zero * top = zero` (any integer multiplied by zero is zero).

## Conditional Refinement

When the analysis encounters a condition `x OP expr` (where `x` is a variable), it should
refine the abstract value of `x` in each branch **only when `expr` evaluates to `zero`** in
the current abstract state. Refinement when the RHS is non-zero is not required.

When comparing a variable `x` against an expression evaluating to `zero`:

### True branch refinement

| Condition | Refinement |
|-----------|------------|
| `x < 0`  | x' = x ⊓ neg |
| `x > 0`  | x' = x ⊓ pos |
| `x == 0` | x' = x ⊓ zero |
| `x != 0` | if x = zero then x' = bottom, else x' = x |
| `x <= 0` | if x = pos then x' = bottom, else x' = x |
| `x >= 0` | if x = neg then x' = bottom, else x' = x |

### False branch refinement

| Condition (negated) | Refinement |
|---------------------|------------|
| `x >= 0` (¬ x<0)   | if x = neg then x' = bottom, else x' = x |
| `x <= 0` (¬ x>0)   | if x = pos then x' = bottom, else x' = x |
| `x != 0` (¬ x==0)  | if x = zero then x' = bottom, else x' = x |
| `x == 0` (¬ x!=0)  | x' = x ⊓ zero |
| `x > 0`  (¬ x<=0)  | x' = x ⊓ pos |
| `x < 0`  (¬ x>=0)  | x' = x ⊓ neg |

When a condition compares two variables (`x OP y`), apply the above rules to both
variables independently using the other's sign value, only when the other evaluates to
`zero`.

## Correctness Criteria

### Statements

- **Assignments**: The abstract sign of the target variable becomes the abstract
  evaluation of the right-hand side expression using the transfer functions above.
- **Conditionals**: The result state is the join of the states produced by analyzing
  the true branch (with the condition's refinement applied) and the false branch
  (with the negated condition's refinement applied).
- **Loops**: The result state after a loop must be a fixed point of the loop body
  analysis. That is, if you enter the loop body from this state (applying the
  condition's true refinement), analyze the body, and join the result with the
  pre-loop state, you must get the same state back. The analysis should produce
  the *least* such fixed point. After the loop exits, the condition's false
  refinement is applied.
- **Function calls**: The return value of a call depends on the abstract signs of
  the actual arguments passed to the callee.

### Context Sensitivity

The analysis must be **context-sensitive**: two calls to the same function with
different abstract argument sign tuples must be analyzed independently and may
produce different return signs. A context-insensitive analysis that merges all
call contexts will produce overly imprecise results and fail the test cases.

### Recursive Functions

For recursive or mutually recursive functions, the analysis must produce return
signs that are self-consistent: re-analyzing the function body under those return
sign assumptions yields the same result. The result must be the least such
consistent assignment.

### Scope

- Each function has its own local scope. Variables in a called function are not visible to
  the caller.
- Function parameters are the only input; return values are the only output.
- The entry point is `main()`, which takes no arguments.

## Output Specification

The analyzer must be an executable Python script at `/app/analyzer.py`, invoked as:

```
python3 /app/analyzer.py <program_file>
```

It must print to stdout a JSON object mapping each local variable name in `main` to its
sign at the point of `main`'s `return` statement. Sign values must be one of the strings:
`"bottom"`, `"neg"`, `"zero"`, `"pos"`, `"top"`.

Example output:
```json
{"x": "pos", "y": "neg", "z": "top"}
```
