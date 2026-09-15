A Python sqllogictest runner at `/app/slt_runner.py` executes `.slt` test suites against SQLite. It correctly handles all standard record types (statement, query, system, let), sort modes (nosort, rowsort, valuesort), hash-threshold, variable substitution, conditions (onlyif/skipif), retry, and include directives.

The runner lacks `--override` mode — the workflow feature that automatically rewrites `.slt` files in-place with actual database output when expected results are stale. This is a critical production feature used by RisingWave, DataFusion, Databend, and every other major adopter of sqllogictest. Without it, developers must manually update hundreds of test expectations after schema or behavior changes.

The source code of `sqllogictest-rs` (the canonical Rust reference implementation) is at `/app/reference/`. Study `runner.rs` — particularly `update_record_with_output` (~line 1755) and `update_test_file` (~line 1591) — and `parser.rs` to understand the correct override semantics, including record-type conversions, error format decisions, and structure preservation.

Design and implement `--override` for `/app/slt_runner.py`. When invoked as `python3 /app/slt_runner.py <file> --override`, the runner must execute all records, then rewrite the file so that re-running without `--override` passes. Key design decisions you must evaluate from the reference implementation:

- How to handle record-type mismatches (e.g., `statement error` that succeeds, `statement ok` that errors, `statement count` with wrong count)
- When to use inline regex error format vs. multiline error format with `----` and double-blank-line terminator
- How sort modes and hash-threshold interact with the override output
- How to preserve file structure (comments, blank lines, conditions, control directives) while rewriting result sections
- How to handle `halt` (records after halt written as-is without execution)
- How to correctly terminate different section types (query results vs. system stdout vs. multiline errors)

The runner must exit 0 after a successful override and still emit its JSON report to stdout.