A SQL-on-FHIR ViewDefinition evaluator at `/app` has multiple defects causing its compliance test suite to fail. Fix the codebase so that every test passes.

**Project layout:**

- `/app/src/evaluator.ts` -- Core evaluation engine
- `/app/src/fhirpath-utils.ts` -- FHIRPath expression evaluation and constant processing
- `/app/src/types.ts` -- TypeScript interfaces
- `/app/src/cli.ts` -- Test runner CLI
- `/app/testdata/` -- 14 JSON compliance test files (104 tests total)

**Running the suite:**

```
cd /app && npm install && npx ts-node src/cli.ts run testdata/test_*.json
```

The CLI emits a JSON report to stdout with `total`, `passed`, `failed`, and `errors` counts, plus per-test `results`. It exits 0 only when every test passes.

Each test file supplies FHIR resources, a ViewDefinition object, and either expected output rows (`expect`), an expected row count (`expectCount`), or `expectError: true`. The test data files are the specification -- your fixes must make the evaluator produce matching output for every case, including cases where the correct behavior is to raise an error.

Defects span multiple source files and affect several independent subsystems. Some defects cause silently wrong output rather than errors, and some interact with each other. Examining which tests fail and how the produced output differs from the expected output is essential for diagnosis.

**Success criterion:** `cd /app && npm install && npx ts-node src/cli.ts run testdata/test_*.json` exits with code 0 -- all 104 tests pass with zero failures and zero errors.
