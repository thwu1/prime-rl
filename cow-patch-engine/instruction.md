Implement a copy-on-write immutable state engine with JSON patch generation in TypeScript. The skeleton files at `/app/src/engine.ts` and `/app/src/patches.ts` define the required function signatures. Type definitions are in `/app/src/types.ts`; re-exports are in `/app/src/index.ts`.

## Required Functions

**`produce(base, recipe)`** in `/app/src/engine.ts` — Accept a plain-object or array `base` and a `recipe` callback. The `recipe` receives a value that can be mutated freely. After the recipe runs, return a new immutable state reflecting those mutations. Observable contracts:

- If no mutations occur, return `base` itself (same reference).
- Subtrees not affected by any mutation must share identity (`===`) with the corresponding subtree in `base`.
- `base` must never be mutated.
- The returned state and all nested plain objects/arrays must be recursively `Object.freeze`d.
- If `recipe` returns a non-`undefined` value that is not the value it received, use the returned value as the result instead of computing from mutations.

**`produceWithPatches(base, recipe)`** in `/app/src/engine.ts` — Same observable behavior as `produce`, but returns `[result, patches, inversePatches]`. Patches use the format `{op: "add"|"replace"|"remove", path: (string|number)[], value?}`. Object keys in paths are strings; array indices are numbers. The following must hold for every call: `applyPatches(base, patches)` deeply equals `result`, and `applyPatches(result, inversePatches)` deeply equals `base`. Patch `value` fields must not alias internal state — they must be independent copies.

**`applyPatches(base, patches)`** in `/app/src/patches.ts` — Apply an array of patches to produce a new state without mutating `base`. Target-type dispatch:

- **Objects**: `add`/`replace` assign at key; `remove` deletes the key.
- **Arrays**: `add` splices at index (`"-"` appends); `remove` splices out; `replace` assigns.
- **Maps**: `add`/`replace` via `.set()`; `remove` via `.delete()`.
- **Sets**: `add` via `.add()`; `remove` via `.delete(patch.value)`.

Patch values must be deep-cloned before insertion. Throw on any path segment equal to `"__proto__"`, `"constructor"`, or `"prototype"`. Throw on unresolvable paths.

## Build

Compile with `cd /app && npm install && npx tsc`. Output goes to `/app/dist/`.
