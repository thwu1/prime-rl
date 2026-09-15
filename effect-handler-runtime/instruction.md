`/app/effects.py` contains a skeleton API for an algebraic effect handler runtime in Python. The `Effect` class is implemented; `perform()` and `handle()` raise `NotImplementedError`.

Reference implementations of key effect handler patterns are provided as SWI-Prolog programs in `/app/reference/`, written using Prolog's built-in delimited continuation primitives (`reset/3` and `shift/1`). SWI-Prolog is pre-installed as `swipl`. Run these reference programs to observe the exact semantics your Python implementation must match — the test suite dynamically compares your implementation's behavior against the Prolog reference output for state effects, handler result composition, handler shadowing, and emit/collect patterns.

## Semantics

- `perform(effect, arg)` transfers control to the nearest enclosing handler for that effect. Returns whatever value the handler passes to `resume()`. Raises `RuntimeError` if no handler is in scope.

- `handle(body_fn, handlers)` runs `body_fn()` with the given handlers active. `handlers` maps `Effect` instances to functions `(arg, resume) -> result`. Calling `resume(value)` continues the body from the `perform()` call site with `perform()` returning `value`. `resume()` itself returns the body's eventual result (or a nested handler's result). If the handler does not call `resume`, the body is abandoned and `handle()` returns the handler's return value directly.

- Handler scoping: inner handlers shadow outer handlers for the same effect. Effects performed by the handler function itself propagate to handlers *above* the current one, never to itself. Effects not in `handlers` propagate to enclosing `handle()` calls.

- Multi-shot: `resume` may be called zero, one, or multiple times. Each call produces an independent continuation of the body.

## Constraints

- Do not modify test files or Prolog reference programs
- Write your implementation to `/app/effects.py`, preserving the existing `Effect` class API
- Standard library only (no pip packages)