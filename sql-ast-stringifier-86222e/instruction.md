A multi-dialect SQL transpiler at `/app/` parses SQL into ASTs via a Peggy PEG grammar, optionally transforms ASTs between MySQL, PostgreSQL, and Snowflake dialects, and stringifies them back to SQL.

Build pipeline:

```
cd /app && npm install
npx peggy --format commonjs -o src/generated/parser.js grammar/sql.pegjs
npx tsc
```

The transpiler has defects and missing capabilities. Repair and extend it until all 42 test cases pass:

```
node /tests/test_runner.js && pytest /tests/test_state.py
```

The test suite validates:

- AST-to-SQL stringification across three dialects (identifier quoting, clause assembly, expression rendering)
- Parse-then-stringify round-trips for compound boolean expressions, CASE/WHEN/ELSE, aggregate and window functions with frame clauses, EXISTS subqueries, PostgreSQL chained `::` casts, JOINs with ON conditions, UNION chains, CTEs, ORDER BY with NULLS, and LIMIT/OFFSET
- Cross-dialect transpilation of function names and cast syntax between MySQL, PostgreSQL, and Snowflake

Constraints:

- Do not modify `/app/src/types.ts` or any file under `/tests/`
- Do not add runtime dependencies beyond those in `/app/package.json`
- All 42 test cases must pass
