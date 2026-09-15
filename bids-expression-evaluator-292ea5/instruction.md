The BIDS Schema Expression Language evaluator at `/app/src/` is a TypeScript implementation of the expression language used by the Brain Imaging Data Structure (BIDS) validator. It consists of a lexer (`/app/src/lexer.ts`), parser (`/app/src/parser.ts`), and evaluator (`/app/src/evaluator.ts`) that process expressions involving arithmetic, logic, string manipulation, property/index access, and built-in functions.

The file `/app/expression_tests.yaml` contains the canonical test suite: a list of 77 expressions with their expected results, covering null propagation, arithmetic, string operations, array operations, and all built-in functions. The test runner at `/app/src/run_tests.ts` loads these tests, evaluates each expression against a minimal context (where `sidecar` is an empty object), and outputs JSON results to stdout.

To install dependencies and run the test suite:

```
cd /app && npm install && npx ts-node src/run_tests.ts
```

The output JSON has the shape `{"total": N, "passed": N, "failed": N, "errors": [...]}`.

The evaluator currently fails multiple test cases due to bugs distributed across the lexer, parser, and evaluator modules. Fix all bugs so that every test case passes.

The expression language supports:

- Arithmetic: `+`, `-`, `*`, `/`, `%`; string concatenation via `+`
- Comparison: `==`, `!=`, `<`, `<=`, `>`, `>=`
- Logical: `&&`, `||`, `!` with null-aware short-circuit semantics
- Containment: `expr in expr`
- Member access: `obj.prop`; index access on arrays and strings: `val[i]`
- Literals: numbers, single/double-quoted strings, `true`, `false`, `null`, arrays `[...]`, objects `{}`
- Built-in functions: `match`, `length`, `type`, `intersects`, `allequal`, `substr`, `sorted`, `min`, `max`, `unique`, `index`, `count`, `exists`

The `expression_tests.yaml` file is the authoritative specification for correct behavior, including null propagation rules and function return value semantics.

**Success criteria:**

1. `npx ts-node src/run_tests.ts` outputs JSON with `"failed": 0`.
2. `npx tsc --noEmit` exits with code 0 (no TypeScript compilation errors).
