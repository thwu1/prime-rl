Implement a Python algebraic effect handler system with multi-shot delimited continuations and composable handlers. The system must implement Koka-style `ctl` operation semantics where captured continuations can be invoked zero times (failure), once (tail-resumptive), or multiple times (non-deterministic exploration).

## Environment

An oracle binary at `/app/reference/effects_oracle` is the authoritative reference for all handler composition semantics. Explore its capabilities and study its outputs — your implementation must match them exactly.

Koka source files in `/app/koka_reference/` define the handler patterns and their composition algebra. Specification notes are in `/app/spec/`.

## Deliverables

### `/app/effects.py`

Algebraic effect handler library supporting:
- Non-deterministic choice and failure (zero-shot abandon)
- Mutable state effects (get/set)
- Reader effects (ask for a contextual value)
- Multi-shot resume with depth-first, lexicographic exploration order
- Correct handler composition: nesting order of handlers determines shared-vs-local state semantics as demonstrated by the oracle and Koka reference programs

### `/app/solver.py`

N-Queens constraint solver expressing non-deterministic choice and backtracking failure purely as algebraic effects handled by multi-shot continuations. Must expose `solve_queens(n)` returning all valid placements as lists of 1-indexed row positions (one per column), in lexicographic order. Must work for any `n >= 1`.

When executed directly (`python3 /app/solver.py`), must print exactly:
```
queens(5): 10 solutions
first: 1,3,5,2,4
queens(8): 92 solutions
first: 1,5,8,6,3,7,2,4
```

### `/app/programs.py`

Handler composition demonstrations matching the oracle's output. Must expose:
- `choice_xor()` — multi-shot resume with boolean XOR
- `state_choice()` — state handler outside choice handler (shared state across branches)
- `choice_state()` — choice handler outside state handler (local state per branch)
- `compose_triple_shared()` — reader + state + choice with shared state
- `compose_triple_local()` — reader + state + choice with local state

Consult the oracle and the Koka reference source for the precise semantics of each scenario.