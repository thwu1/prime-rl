# CESK Machine and 0-CFA Specification

This document specifies the formal semantics for the ANF lambda calculus
defined in `lang.py`, including the CESK interpreter and 0-CFA analyzer.

## 1. Language Summary

The language is A-Normal Form (ANF) lambda calculus with:
- Lambda abstraction, function application, let binding
- Recursive binding (`letrec`)
- Conditionals (`if`)
- Mutation (`set!`)
- First-class continuations (`call/cc`)
- Primitives: `+`, `-`, `*`, `=`, `<`

Each `lambda` term has a unique integer label (assigned in declaration
order by the parser, starting from 1).

## 2. CESK Machine

### 2.1 Domains

```
State  = Exp × Env × Store × Kont

Env    = Var → Addr                  (partial map)
Store  = Addr → Value                (partial map)
Addr   = ℕ                          (fresh integers)

Value  = Int(z)                      (integer)
       | Bool(b)                     (boolean)
       | Void                        (unit value from set!)
       | Closure(lam, env)           (function closure)
       | Cont(kont)                  (reified continuation)

Kont   = Halt
       | LetK(var, body, env, kont)  (let continuation frame)
```

### 2.2 Injection

```
inject(program) = (program, {}, {}, Halt)
```

### 2.3 Atomic Evaluation: A(aexp, ρ, σ) → Value

```
A(IntLit(z), ρ, σ)       = z
A(BoolLit(b), ρ, σ)      = b
A(Var(v), ρ, σ)           = σ(ρ(v))
A(Lam(params, body), ρ, σ) = Closure(lam, ρ)
A(PrimOp(op, args), ρ, σ) = δ(op, A(args[0], ρ, σ), ..., A(args[n], ρ, σ))
```

where `δ` maps primitive names to their operations:
- `δ(+, a, b) = a + b`
- `δ(-, a, b) = a - b`
- `δ(*, a, b) = a × b`
- `δ(=, a, b) = (a == b)`  → boolean
- `δ(<, a, b) = (a < b)`   → boolean

### 2.4 Transition Rules: step(ς) → ς'

**Atomic expression (return to continuation):**
```
step(aexp, ρ, σ, κ) = applyKont(κ, A(aexp, ρ, σ), σ)
```
Applies when ctrl is IntLit, BoolLit, Var, Lam, or PrimOp.

**Let binding:**
```
step(Let(v, rhs, body), ρ, σ, κ) = (rhs, ρ, σ, LetK(v, body, ρ, κ))
```

**Function application:**
```
step(App(f, [e₁,...,eₙ]), ρ, σ, κ) =
  applyProc(A(f, ρ, σ), [A(e₁, ρ, σ), ..., A(eₙ, ρ, σ)], σ, κ)
```

**Conditional:**
```
step(If(cond, eₜ, eₑ), ρ, σ, κ) =
  if A(cond, ρ, σ) ≠ #f then (eₜ, ρ, σ, κ) else (eₑ, ρ, σ, κ)
```
Only `#f` (boolean false) is falsy. `0`, `Void`, etc. are truthy.

**Mutation:**
```
step(SetBang(v, aexp), ρ, σ, κ) =
  let val = A(aexp, ρ, σ) in
  let σ' = σ[ρ(v) ↦ val] in
  applyKont(κ, Void, σ')
```

**Recursive binding:**
```
step(Letrec([(v₁,e₁),...,(vₙ,eₙ)], body), ρ, σ, κ) =
  let a₁,...,aₙ = fresh addresses in
  let ρ' = ρ[vᵢ ↦ aᵢ] in
  let valᵢ = A(eᵢ, ρ', σ) in       -- evaluate in extended env
  let σ' = σ[aᵢ ↦ valᵢ] in
  (body, ρ', σ', κ)
```

**call/cc:**
```
step(CallCC(f), ρ, σ, κ) =
  let proc = A(f, ρ, σ) in
  let cc = Cont(κ) in
  applyProc(proc, [cc], σ, κ)
```

### 2.5 Applying Procedures

```
applyProc(Closure(Lam(params, body), ρ_c), [v₁,...,vₙ], σ, κ) =
  let a₁,...,aₙ = fresh in
  let ρ' = ρ_c[paramᵢ ↦ aᵢ] in
  let σ' = σ[aᵢ ↦ vᵢ] in
  (body, ρ', σ', κ)

applyProc(Cont(κ_saved), [v], σ, κ) =
  applyKont(κ_saved, v, σ)           -- discards current κ
```

### 2.6 Applying Continuations

```
applyKont(Halt, v, σ) = v            -- terminal; return final value

applyKont(LetK(var, body, ρ, κ), v, σ) =
  let a = fresh in
  let ρ' = ρ[var ↦ a] in
  let σ' = σ[a ↦ v] in
  (body, ρ', σ', κ)
```

### 2.7 Running

```
run(text):
  prog = parse(text)
  ς = inject(prog)
  while ς is a State:
    ς = step(ς)
  return ς                            -- the final value
```

## 3. 0-CFA (Zeroth-Order Control-Flow Analysis)

### 3.1 Overview

0-CFA computes a conservative mapping from each variable name to the
set of lambda labels that may flow to that variable at runtime.

The analysis tracks only lambda closures (identified by label).
Primitive values (integers, booleans) are not tracked.

### 3.2 Abstract Domains

```
FlowMap = VarName → 𝒫(Label)
Label   = ℕ  (the label field of a Lam node)
```

### 3.3 Flow Rules

Define `flow_of(exp)` as the set of lambda labels that exp may evaluate to.
The `flow` map is updated as a side effect.

```
flow_of(Lam(params, body, L))     = {L}
flow_of(Var(v))                    = flow[v]
flow_of(IntLit(_))                 = {}
flow_of(BoolLit(_))                = {}
flow_of(PrimOp(_, args))           = {}         (process args for side effects)

flow_of(Let(v, rhs, body))         : flow[v] ⊇ flow_of(rhs)
                                     return flow_of(body)

flow_of(App(f, [e₁,...,eₙ]))       : for each L ∈ flow_of(f):
                                       let Lam(params, body_L) = lambdas[L]
                                       flow[paramᵢ] ⊇ flow_of(eᵢ)
                                       result ⊇ flow_of(body_L)
                                     return result

flow_of(If(c, t, e))               : return flow_of(t) ∪ flow_of(e)

flow_of(Letrec(bindings, body))    : flow[vᵢ] ⊇ flow_of(eᵢ)
                                     return flow_of(body)

flow_of(SetBang(v, val))           : flow[v] ⊇ flow_of(val)
                                     return {}

flow_of(CallCC(_))                 : return {}  (simplified)
```

### 3.4 Fixed-Point Iteration

The analysis iterates until no flow set grows:

```
analyze(text):
  prog = parse(text)
  lambdas = collect all Lam nodes by label
  flow = {} (empty map, all sets start empty)
  repeat:
    old_total = Σ |flow[v]| for all v
    flow_of(prog)   -- updates flow as side effect
    if Σ |flow[v]| == old_total: break
  return flow
```

**Recursion guard:** When processing an `App`, if the callee lambda is
already being processed (on the current call stack), argument-to-parameter
flow still occurs, but the body is not re-entered. This prevents infinite
recursion while maintaining soundness through the outer fixed-point loop.

### 3.5 Assumptions

- Variable names are unique across the program (no shadowing). The
  analysis uses variable names as abstract addresses.
- The analysis need not handle `call/cc` precisely; returning `{}` for
  `CallCC` expressions is acceptable.

## 4. Required API

### `/app/cesk.py`

```python
def run(text: str):
    """Parse and evaluate the program. Return the final value.
    
    Return types: int for integers, bool for booleans.
    Closures and continuations may be returned as any object.
    """
```

### `/app/zcfa.py`

```python
def analyze(text: str) -> dict:
    """Perform 0-CFA. Return {variable_name: set_of_lambda_labels}.
    
    Keys are strings (variable names).
    Values are sets of ints (lambda labels from Lam.label).
    Only include variables that have non-empty flow sets,
    or include all variables with potentially empty sets — both are acceptable.
    """
```

## 5. Examples

### CESK Example
```scheme
(let ((f (lambda (x) (+ x 1))))
  (f 10))
```
`run(...)` returns `11`.

### 0-CFA Example
```scheme
(let ((id (lambda (v) v)))
  (let ((f (lambda (a) (+ a 1))))
    (let ((g (lambda (b) (* b 2))))
      (let ((h (id f)))
        (let ((j (id g)))
          42)))))
```
Labels: `id`=Lam#1, `f`=Lam#2, `g`=Lam#3.

`analyze(...)` should produce (at minimum):
- `flow['id']` ⊇ `{1}`
- `flow['f']`  ⊇ `{2}`
- `flow['g']`  ⊇ `{3}`
- `flow['v']`  ⊇ `{2, 3}` (id called with both f and g)
- `flow['h']`  ⊇ `{2, 3}`
- `flow['j']`  ⊇ `{2, 3}`
