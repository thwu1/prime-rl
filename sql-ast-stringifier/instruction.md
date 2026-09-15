A TypeScript SQL AST-to-SQL stringifier at `/app/` converts JSON AST nodes into SQL strings using a dispatch-pattern architecture spread across modules in `src/`:

- `expr.ts` — central dispatch routing expression nodes by `type` to registered handlers
- `init.ts` — handler registration wiring dispatch to stringifier modules
- `select.ts` — SELECT clauses, window functions, OVER, ORDER BY, FROM/JOIN, DISTINCT
- `func.ts` — functions, type casts, aggregate functions
- `union.ts` — set operations (UNION/INTERSECT/EXCEPT) and WITH (CTE) clauses
- `binary.ts`, `column.ts`, `case.ts` — binary expressions, column refs, CASE expressions
- `types.ts` — full AST node shape documentation

The CLI at `src/cli.ts` reads a JSON AST from stdin and writes SQL to stdout. Batch mode accepts a JSON array and returns `[{sql, error}, ...]`:

```
cd /app && npm install
echo '<json>' | npx tsx src/cli.ts
```

The stringifier has multiple defects producing incorrect SQL for valid AST inputs. The defects span multiple modules and interact — compound test cases require fixes in different files to pass simultaneously. Every handler-relevant property documented in `types.ts` must be correctly processed by its corresponding stringifier function; several are currently silently dropped or incorrectly transformed.

Identify all defects by studying the type definitions against the handler implementations and running the test suite. Fix the stringifier so it correctly handles all documented AST node properties. Do not modify test files, `cli.ts`, `expr.ts`, `types.ts`, `binary.ts`, `column.ts`, `case.ts`, or `index.ts`.

Success: `bash /tests/test.sh` writes `1.0` to `/logs/verifier/reward.txt`.
