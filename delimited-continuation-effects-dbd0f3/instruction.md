Fix and complete `/app/effects.scm`. The program uses Chez Scheme with the SRFI 226 control features library (source at `/app/lib/`). Run with:

```
chezscheme --libdirs /app/lib --program /app/effects.scm
```

The program defines and tests six components. All 23 embedded tests must report `PASS` with the final `TOTAL` line showing `23 tests, 0 failures`.

**`shift` / `reset`** — `(reset expr ...)` delimits a computation. `(shift k expr ...)` captures the continuation up to the nearest `reset`, binds it to `k`, and evaluates the body. Applying `k` must correctly resume the captured computation, including repeated application like `(k (k 4))` and nested shifts.

**`shift-at` / `reset-at`** — Tagged variants. `(reset-at tag expr ...)` delimits with an explicit prompt tag. `(shift-at tag k expr ...)` captures up to the nearest matching `reset-at`.

**`run-with-state`** — `(run-with-state proc seed)` calls `proc` with `get` and `put` procedures for a state cell initialized to `seed`. Returns the final result. Nested calls must maintain independent state cells. State modifications within one nondeterministic branch must not be visible in other branches.

**`amb` / `fail` / `collect-all`** — `(collect-all thunk)` collects all nondeterministic results from `thunk` into a list. `(amb choices)` selects each element from `choices` in separate result branches, explored left-to-right. `(fail)` prunes the current branch. `dynamic-wind` guards must fire correctly during backtracking.

**`for-each->stream`** — `(for-each->stream for-each-proc seq)` converts a `for-each`-style iteration into a lazy stream. The provided stream primitives must not be modified.

**`run-with-handler` / `perform`** — `(run-with-handler tag ret-handler eff-handler thunk)` evaluates `(thunk)`. On normal return with value `v`, returns `(ret-handler v)`. When `(perform tag val)` is called, `eff-handler` receives the delimited continuation `k` and `val`. Calling `(k result)` resumes computation with `result` as the return value of `perform`. If `eff-handler` does not call `k`, its return value becomes the overall result (still passed through `ret-handler`). Multiple effects within one handler scope must work correctly.

**Success criteria**: All `TEST` lines show `PASS`; the `TOTAL` line shows `23 tests, 0 failures`.
