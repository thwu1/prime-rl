`/app` contains three coupled TypeScript subsystems for BIDS-style data validation. All three have defects that must be resolved.

The **expression evaluator** (`/app/src/lexer.ts`, `parser.ts`, `evaluator.ts`, `functions.ts`) implements a lexer→parser→AST→evaluator pipeline for the BIDS expression language. It supports arithmetic, logical, and comparison operators with null propagation, member and index access, the `in` operator, and built-in functions (`match`, `intersects`, `sorted`, `allequal`, `type`, `length`, `count`, `min`, `max`, `unique`, `index`, `exists`, `substr`). Correct behavior is specified by 77 test cases in `/app/spec/expression_tests.yaml`.

The **sidecar inheritance resolver** (`/app/src/inheritance.ts`) resolves effective metadata for a data file by walking the dataset directory tree from root to the file's directory. At each directory level, it collects JSON sidecar files whose suffix matches the target and whose entities are a subset of the target file's entities (a sidecar with fewer entities applies more broadly). Metadata is merged so that closer (deeper) sidecars override more distant ones. The resolver is incomplete — it currently examines only the file's immediate directory instead of walking the full ancestor path. Test cases are in `/app/spec/inheritance_tests.json`.

The **validation rule engine** (`/app/src/rule_engine.ts`) loads rules from `/app/spec/validation_rules.yaml`. Each rule has selectors (suffix/datatype/extension lists and entity requirements) and checks (expressions evaluated via the expression evaluator against a file context). A selector matches when all its criteria are met; a rule matches when any selector matches. Checks reference the context via paths like `sidecar.RepetitionTime`, `entities.task`, `columns`. Checks may have a `depends_on` index referencing an earlier check; a dependent check is skipped when its dependency failed. A file passes when it has zero error-level issues; warnings do not cause failure.

**Commands:**
```
cd /app && npm install && npx tsx run_tests.ts
cd /app && npx tsx resolve.ts spec/inheritance_tests.json
cd /app && npx tsx validate.ts spec/test_contexts.json
```

**Success criteria:**
- `run_tests.ts`: all entries must have `"passed": true`
- `resolve.ts`: all entries must have `"passed": true`
- `validate.ts`: output must show correct `matched_rules`, `issues`, and `passed` for each test context
