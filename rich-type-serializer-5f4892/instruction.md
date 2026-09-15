A rich-type JSON serializer library at `/app/` extends `JSON.stringify`/`JSON.parse` to handle non-JSON types (`Date`, `Map`, `Set`, `BigInt`, `RegExp`, `URL`, `Error`, typed arrays, custom-registered classes, symbols, and custom transformers). It produces `{ json, meta }` output and supports circular reference detection, referential identity preservation across serialization boundaries, and an optional deduplication mode (`dedupe: true`).

The library contains multiple interacting bugs across its source modules that cause serialization and deserialization failures. Some bugs are isolated; others interact — fixing one may reveal failures that depend on another being correct. The bugs span different subsystems and require understanding how the serialization pipeline transforms, annotates, traverses, and restores complex object graphs.

All source code is under `/app/src/`. Diagnose and fix every bug so the full test suite passes.

**Verification:**

```
cd /app && npm install && npx vitest run
```

The authoritative test suite is at `/app/src/index.test.ts`. All tests must pass.

**Success criteria:** `npx vitest run` exits 0 with every test passing.
