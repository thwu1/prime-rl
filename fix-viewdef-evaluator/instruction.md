A SQL-on-FHIR v2 ViewDefinition evaluator at `/app/` contains defects causing it to fail a subset of the official conformance test suite. The evaluator transforms FHIR resources into flat tabular rows per a ViewDefinition specification. It is implemented in TypeScript with source files in `/app/src/`.

Conformance fixtures at `/app/fixtures/` are JSON files each containing input FHIR resources, ViewDefinitions, and expected output rows (or expected errors). The test runner `/app/runner.ts` loads every fixture, evaluates each ViewDefinition, and emits a JSON report on stdout with shape `{ total, passed, failed, results: [{ file, title, passed, error? }] }`.

**Setup**: `cd /app && npm install`

**Run tests**: `cd /app && npx tsx runner.ts`

**Goal**: Diagnose and fix all defects in the source code under `/app/src/` so that every conformance test passes. Do not modify fixture files, the test runner, or `package.json`.

**Success**: `cd /app && npx tsx runner.ts | python3 -c "import sys,json; r=json.load(sys.stdin); sys.exit(0 if r['failed']==0 else 1)"` exits 0.
