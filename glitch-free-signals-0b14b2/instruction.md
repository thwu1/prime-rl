The project at `/app/` contains a broken TypeScript reactive signals library. Fix the implementation in `/app/src/` so that all tests pass.

The library exports `signal()`, `computed()`, `effect()`, `flushEffects()`, and `untracked()` from `/app/src/index.ts`. The public API signatures must not change.

Required semantics:

**Glitch-free evaluation**: In a diamond dependency graph (A->B, A->C, B+C->D), changing A must cause D to recompute exactly once per read, observing consistent values from all upstream computed nodes. Use pull-based lazy evaluation, not eager push-based recomputation.

**Dynamic dependency tracking**: When a computed's set of read dependencies changes between evaluations (e.g. due to a conditional branch), producers that are no longer read must be unsubscribed so that future changes to them do not trigger recomputation.

**Cycle detection**: A computed signal that directly or transitively reads itself must throw an `Error` (not cause a stack overflow) when evaluated.

**Write guards**: Calling `set()` or `update()` on a signal inside a `computed()` callback must throw an `Error`. Writing inside an `effect()` callback must be allowed.

**Computed equality cutoff**: After a computed re-evaluates, if the new output value is equal to the previous output (via the configured equality function, defaulting to `Object.is`), the computed's version must not increment, preventing unnecessary downstream recomputation.

**Effect deduplication**: Each effect must execute at most once per `flushEffects()` call, regardless of how many of its dependencies changed.

**Effect cleanup**: A cleanup function registered via the `onCleanup` callback during an effect's execution must be invoked before the effect's next execution.

**Untracked reads**: Signal reads inside the `untracked()` wrapper must not register as dependencies of the calling consumer.

Source files to modify: `/app/src/graph.ts`, `/app/src/signal.ts`, `/app/src/computed.ts`, `/app/src/effect.ts`, `/app/src/untracked.ts`.

Run tests: `cd /app && npm install && npx tsx /tests/test_harness.ts`

The harness outputs a JSON array of `{name, pass, detail?}` objects. All 17 tests must report `pass: true`.
