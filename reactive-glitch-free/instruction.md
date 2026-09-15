Fix the broken TypeScript reactive state library project at `/app/`. The project must pass three verification stages: type-checking, building, and runtime correctness.

**Type-checking**: `npx tsc --noEmit` must exit 0. The `tsconfig.json` module and resolution settings must be consistent with the project's import conventions and build tooling.

**Building**: `node build.mjs` must produce `/app/dist/index.mjs` as a valid ESM bundle exporting all public API symbols. The esbuild configuration in `build.mjs` has incorrect entry point, output format, output path, target, and platform settings.

**Runtime correctness** — the library re-exports from `/app/src/index.ts`:

From `src/reactive.ts`:
- `createSignal<T>(value: T): [Getter<T>, Setter<T>]` — reactive state. `Getter<T> = () => T`, `Setter<T> = (value: T | ((prev: T) => T)) => void`. No-op when new value is `Object.is`-equal.
- `createEffect(fn: () => void): void` — auto-tracks signal/memo reads; re-executes on dependency change. Supports dynamic dependency sets.
- `createMemo<T>(fn: () => T): Getter<T>` — cached derived value. Glitch-free: re-evaluates only on upstream change. If recomputed value is `Object.is`-equal to cached, downstream must NOT re-execute.
- `batch(fn: () => void): void` — defers all effect execution until `fn` completes.
- `createRoot<T>(fn: (dispose: () => void) => T): T` — ownership scope. `dispose` recursively disposes all nested computations.
- `untrack<T>(fn: () => T): T` — runs `fn` without tracking dependencies.
- `onCleanup(fn: () => void): void` — registers cleanup callback before owning computation re-runs or is disposed.

Glitch-free contract: in a diamond `A -> B, A -> C, B+C -> D`, updating `A` must cause `D` to evaluate exactly once with consistent `B` and `C` values.

Ownership: computations created inside another are owned by it. Disposal is recursive and runs all registered cleanups.

From `src/store.ts`:
- `createStore<T extends object>(initial: T): [T, SetStoreFunction<T>]` — deep reactive state. The returned proxy tracks property reads inside effects, including nested objects recursively. Mutations only through `SetStoreFunction`.
- `SetStoreFunction` supports: `setStore(key, value)` for top-level, `setStore(key1, key2, value)` for nested paths, and `setStore(fn)` for batch updates via a mutable draft proxy.
- Store mutations must trigger effects that depend on changed properties.

Exported types: `Getter<T>`, `Setter<T>`, `SetStoreFunction<T>`.
