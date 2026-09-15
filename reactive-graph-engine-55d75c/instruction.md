A fine-grained reactive system is implemented in `/app/src/reactive.ts`. It exports `createSignal`, `createMemo`, `createEffect`, `createRoot`, `batch`, `untrack`, and `onCleanup`. The current implementation has algorithmic bugs that cause incorrect behavior in non-trivial reactive dependency graphs. Fix the implementation.

**Required interface** (all exported from `/app/src/reactive.ts`):

- `createSignal<T>(value, options?): [Accessor<T>, Setter<T>]` — reactive state. The getter tracks the calling computation. The setter accepts a value or `(prev: T) => T`. Notify observers only when the comparator indicates change (default `===`). `{ equals: false }` disables comparison.

- `createMemo<T>(fn, value?, options?): Accessor<T>` — derived reactive value. Acts as both computation (tracks sources) and signal (has observers). Must evaluate at most once per atomic update even in convergent graphs.

- `createEffect<T>(fn, value?): void` — side-effect computation. Runs after pure computations.

- `createRoot<T>(fn: (dispose) => T): T` — ownership scope. Child computations are cleaned up on disposal.

- `batch<T>(fn: () => T): T` — defers downstream updates until `fn` completes.

- `untrack<T>(fn: () => T): T` — runs `fn` without tracking dependencies.

- `onCleanup(fn: () => void): void` — registers disposal callback on current owner.

**Required behaviors**:

1. In a diamond graph (signal to memo_A, memo_B to memo_C), changing the signal causes memo_C to evaluate exactly once, not once per path.

2. In convergent graphs with N fan-out nodes merging into a single sink, the sink evaluates exactly once per update.

3. If an upstream memo re-evaluates but produces an equal value (per its comparator), downstream dependents must not re-evaluate.

4. When a computation re-executes, its dependency set is rebuilt from scratch. Sources from the prior run but not the current run must be fully detached: the computation removed from those signals' observer lists.

5. Disposing a root (via the dispose callback) must fully detach all owned computations from their sources so they no longer react.

6. `batch` coalesces multiple signal writes into a single propagation wave.

7. Throw when a reactive update loop exceeds 1,000,000 queued updates.

**Setup**: `cd /app && npm install`

**Success criteria**: All tests in `/tests/test_state.py` pass.
