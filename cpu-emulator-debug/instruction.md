A MOS 6502 CPU emulator at `/app/cpu6502.py` contains multiple implementation defects across its instruction set. An unmodified copy is preserved at `/app/cpu6502_original.py`. A basic test runner exists at `/app/run_tests.py` and a small set of sample test vectors (SingleStepTests JSON format) are at `/app/test_vectors/`.

Comprehensive per-opcode test suites for the NMOS 6502 are maintained in the SingleStepTests/65x02 repository on GitHub.

Produce the following deliverables:

- **`/app/cpu6502.py`** — The corrected emulator. Every opcode it implements must pass all corresponding authoritative test vectors.

- **`/app/conformance.db`** — A SQLite3 database with two tables:
  - `opcode_results(opcode TEXT PRIMARY KEY, mnemonic TEXT, addressing_mode TEXT, total_tests INTEGER, passed INTEGER, failed INTEGER)` — post-fix per-opcode results.
  - `bugs(id INTEGER PRIMARY KEY, severity TEXT, category TEXT, root_cause TEXT, affected_opcodes TEXT, fix_description TEXT)` — `severity` must be `'critical'`, `'major'`, or `'minor'`.

- **`/app/bug_severity_ranking.json`** — JSON array sorted by decreasing severity. Each element: `{"id": int, "severity": "critical"|"major"|"minor", "affected_opcode_count": int, "justification": string}`. Assess each defect's blast radius considering how many opcodes it affects, whether it corrupts control flow or data, and whether failures are silent or observable.

- **`/app/discriminating_tests.json`** — JSON array of SingleStepTests-format test cases (each with `"name"`, `"initial"`, `"final"` keys; initial/final contain `"pc"`, `"s"`, `"a"`, `"x"`, `"y"`, `"p"`, `"ram"`). One test per identified defect; each must fail on the original emulator and pass on the corrected one.

- **`/app/emulator_changes.patch`** — Unified diff of all changes between the original and corrected emulator.