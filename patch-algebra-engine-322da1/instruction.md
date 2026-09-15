The project at `/app/` contains a TypeScript patch algebra engine for Immer-style immutable state patches. The module at `/app/src/patch-engine.ts` exports functions operating on Immer-format patches (`{op, path, value}` where `path` is an array of `string | number`). Type definitions in `/app/src/types.ts` must not be modified.

The implementation has multiple bugs and partially broken functions. Fix all bugs and complete all implementations so every exported function satisfies its contract:

**`toRFC6902` / `fromRFC6902`**: Bidirectional conversion between Immer array-path and RFC-6902 string-path format. Segments escaped per RFC 6901: `~` → `~0`, `/` → `~1`. Empty string path `""` = document root (empty array); path `"/"` = single segment `""`. Round-tripping must preserve segment types and values including segments containing `~`, `/`, or literal `~1`.

**`isPathPrefix` / `isPathPrefixStrict`**: Path prefix testing with type-strict comparison: numeric `0` ≠ string `"0"`.

**`compressPatches`**: Minimize a patch sequence. Same-path rules: replace+replace → last replace; add+replace → add with new value; add+remove → cancel; replace+remove → remove; remove+add → replace. A `remove` must prune all accumulated patches on strict descendant paths.

**`detectConflicts`**: Detect conflicts between concurrent patch branches. Write-write: same path modified by both. Delete-write: A removes exact path or ancestor of B's target. Write-delete: B removes exact path or ancestor of A's target. Returns `{type, pathA, pathB, patchIndexA, patchIndexB}` per conflict.

**`rebasePatches`**: Transform `patches` over already-applied `over` patches. Drop patches whose target was removed by `over` (exact or ancestor). Shift array indices when `over` inserts or removes elements at preceding positions in the same parent array.

**`applyPatches`**: Apply patch sequence to a JSON state tree, returning new state without mutating input. Object targets: `add`/`replace` set key, `remove` deletes key. Array targets: `add` inserts at index with splice semantics (shifting subsequent elements up), `remove` deletes at index (shifting elements down). Empty path targets document root for all operations.

**`invertPatches`**: Given patches and pre-application state, produce inverse patches that undo changes when applied in reverse order. Inverse of `replace`: `replace` with old value at that path. Inverse of `add`: `remove`. Inverse of `remove`: `add` with the value that existed. For multi-patch sequences, intermediate state after each patch must be tracked to capture correct old values at each step. The returned inverse patches must be in reverse order relative to the input.

Run `npm install` in `/app/` before testing. Use `npx tsx` to execute TypeScript.
