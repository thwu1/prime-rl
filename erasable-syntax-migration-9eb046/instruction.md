A TypeScript project at `/app/` uses non-erasable syntax throughout its codebase. The `tsconfig.json` enforces `erasableSyntaxOnly: true`, causing `tsc` to reject the source files. The project targets `ES2022`.

The source files contain `enum` declarations (numeric with reverse mappings, string, heterogeneous, and `const`), `namespace` blocks with runtime code (including namespace-enum merging and namespace-class merging), parameter properties in class constructors, and `import X = Y.Z` alias syntax.

Refactor all TypeScript source files under `/app/src/` so that `npx tsc` compiles successfully without modifying `tsconfig.json` or `package.json`. The refactored code must preserve **identical runtime behavior** — `node dist/main.js` must produce JSON output matching the original semantics exactly.

**Behavioral contracts:**

- Numeric enum members retain bidirectional (reverse) mapping: value-to-name lookup must work for numeric members only.
- Heterogeneous enums produce reverse mappings only for numeric members; string members have no reverse entry.
- String enum replacements must not introduce reverse mappings.
- Const enum values must evaluate to the same numeric constants.
- Merged namespace functions remain accessible as methods on the same object that holds enum-like values.
- `Object.keys()` filtering on replacement objects must yield the same results as on original compiled enum objects.
- Classes that used parameter properties must preserve identical member initialization semantics. The `TrackedComponent` base class dynamically installs per-instance property getter/setters in its constructor to record mutations. Derived class instances must record the same mutation history after migration — the observable number and content of tracked mutations must not change, including mutations from post-construction property updates.
- Namespace-exported classes remain constructible via the original dotted path.
- Namespace-class merged factory methods and utilities remain callable on the same constructor object.
- The `ServiceRegistry`, `Registry.createEntry()`, and all cross-module type contracts must produce identical data structures.

**Files:**
- `/app/tsconfig.json` — do not modify
- `/app/package.json` — do not modify
- `/app/src/protocol.ts` — enums and namespace-enum merges
- `/app/src/transport.ts` — parameter properties, namespace with class
- `/app/src/middleware.ts` — tracked-property base class, parameter properties, namespace-class merge
- `/app/src/registry.ts` — namespace with interface/function, import aliases
- `/app/src/main.ts` — entry point producing JSON output

**Verification:** `npx tsc` exits 0; `node dist/main.js` produces valid JSON with all expected keys and values matching original semantics.
