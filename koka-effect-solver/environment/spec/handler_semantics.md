# Effect Handler Composition Semantics

This document describes the semantics of algebraic effect handler composition
as implemented by the reference oracle and the Koka reference programs.

## Choice-All Handler

The `choice-all` handler explores all branches of a non-deterministic
computation via multi-shot resume. When `choice()` is performed, the handler
resumes the captured continuation twice — first with `False`, then with
`True` — and concatenates the result lists:

    ctl choice() resume(False) ++ resume(True)

A `return(x)` clause wraps each successful result in a singleton list `[x]`.
Failed branches (zero-shot: no resume) produce `[]`.

Exploration order is depth-first. For the `xor` computation
(`choice() XOR choice()`), branch exploration proceeds:

    p=False, q=False  →  False XOR False = False
    p=False, q=True   →  False XOR True  = True
    p=True,  q=False  →  True  XOR False = True
    p=True,  q=True   →  True  XOR True  = False

## Handler Composition Order

The nesting order of handlers determines how effects interact. This is
the key insight of algebraic effect handler theory.

### State Outside Choice (Shared State)

When the state handler wraps the choice handler:

    pstate(init) { choice-all { computation } }

all choice branches share a single mutable state cell. The `resume(False)`
call runs the continuation to completion — including all state mutations —
and then `resume(True)` runs the continuation from the choice point but
observes the state left behind by the first branch.

### Choice Outside State (Local/Transactional State)

When the choice handler wraps the state handler:

    choice-all { pstate(init) { computation } }

each choice branch gets its own independent state, freshly initialized
to `init`. Mutations in one branch never affect another.

### The `surprising` Example

    surprising():
      p = choice()
      i = get()
      set(i + 1)
      if i > 0 && p then xor() else False

With **shared state** (state outside):
- Branch p=False: reads state 0, writes 1, returns False
- Branch p=True: reads state 1 (left by previous branch), writes 2, enters xor
- The xor sub-computation adds four more branches (no state changes)
- Total results and final state depend on this sequential execution

With **local state** (choice outside):
- Each branch starts with state=0 independently
- Both p=False and p=True read state 0, so `i > 0` is always False

## Three-Handler Composition

The `compose-triple` scenario adds a reader effect:

    triple():
      r = ask()          -- reader value (constant)
      p = choice()       -- non-deterministic choice
      s = get()          -- current state
      set(s + r)         -- update state by reader value
      if p then s+r else s

The reader value is always constant regardless of handler order. The
interaction between state and choice follows the same shared-vs-local
semantics described above.

## Resume Semantics Summary

- **Zero-shot** (failure): continuation is never called; handler returns
  directly (e.g., `[]` for failed branches)
- **Single-shot** (tail-resumptive): continuation called exactly once;
  behaves like a regular function call
- **Multi-shot**: continuation called multiple times; each call runs
  independently from the capture point, but shared state (if the state
  handler is outside) persists across calls
