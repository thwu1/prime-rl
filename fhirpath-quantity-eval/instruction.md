A FHIRPath quantity expression evaluator lives at `/app/`. It evaluates arithmetic and comparison expressions involving quantities with calendar duration units (e.g., `year`, `months`, `day`) and UCUM measurement units (e.g., `'kg'`, `'m'`, `'s'`, `'d'`).

The project contains source code under `/app/src/`, test suites under `/app/test/` and `/tests/`, and a specification document at `/app/spec/quantity_semantics.md` describing the correct evaluation semantics.

The source code has defects that cause test failures, and it is missing functionality described in the specification. Diagnose and fix all defects, and implement all missing functionality in `/app/src/` so that:

1. The built-in test suite passes: `cd /app && npm install && npm test`
2. The external test suite passes: `pytest /tests/test_state.py`

Do not modify any files under `/app/test/`, `/app/spec/`, or `/tests/`. The specification document is authoritative for correct behavior.
