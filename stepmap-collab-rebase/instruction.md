A TypeScript collaborative text editing engine at `/app/` implements position mapping, document transformation, collaborative rebase (operational transform), transform compaction, change span computation, and undo/redo history management. The system enables multiple concurrent clients to edit a shared document while preserving convergence, cursor positions, and edit history correctness.

The implementation contains multiple interrelated bugs across the source files in `/app/src/`. Bugs span low-level position arithmetic, flag logic, algorithmic sequencing, missing code paths, cross-module invariant violations, and incorrect coordinate system transformations. Some are single-expression errors; others require understanding how modules interact — for example, how position recovery through mirror pairs depends on correct inverse computation, or how step inversion must be recomputed (not merely remapped) after collaborative rebase to preserve round-trip correctness.

Fix all bugs so the full test suite passes.

**Runtime**: The project uses ES modules. Install `tsx` globally (`npm install -g tsx@4.19.4`) to run TypeScript directly.

**Test suite**: `/app/src/run_tests.ts` executes all tests and emits a JSON object on stdout:
```json
{"results": [{"group": "...", "name": "...", "passed": true/false, "error": "..."}]}
```

**Success criteria**: Every entry in the `results` array must have `"passed": true`. Verify with `tsx /app/src/run_tests.ts`.
