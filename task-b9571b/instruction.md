Implement a production-quality sqllogictest runner at `/app/sqllogictest_runner.py` for DuckDB that supports the extended format including dual-execution plan verification.

The sqllogictest format encodes SQL statements alongside expected results for automated database conformance testing. DuckDB extends the standard format with multi-connection execution via named database cursors sharing a single instance, connection lifecycle management via `reconnect`, optimizer plan verification through regex-matched EXPLAIN output, query label equivalence via MD5, control flow constructs with variable substitution, and mode directives for controlling verification and execution behavior.

Your runner must parse `.test` files, execute SQL against DuckDB, and verify all results — including the interplay between features such as named connections within loops, regex-matched multi-line EXPLAIN output, negative regex assertions (`<!REGEX>:`), hash-threshold-based automatic result hashing, and data persistence across reconnection boundaries.

Critical capabilities that require deep understanding of DuckDB's execution model:

- **Dual-execution plan verification** (`mode verify`/`mode noverify`): When active, independently re-execute each query with DuckDB's query optimizer disabled and assert result set equivalence with the optimized execution. This mechanism catches optimizer bugs by comparing execution paths. You must determine the correct DuckDB API to control optimizer state, handle proper state restoration, and correctly compare results accounting for the fact that different execution plans may return rows in different orders.

- **Execution flow control** (`mode skip`/`mode unskip`): Conditionally suspend execution of all directives while still processing mode directives. Must correctly handle nested control flow constructs (loops/foreach) within skipped blocks without executing their bodies.

- **Connection pool architecture**: Named connections are cursors over a shared database; `reconnect` destroys all cursors while the database instance — and all persistent state — survives. Getting this lifecycle wrong manifests as subtle data loss or stale cursor bugs.

A brief format reference is at `/app/FORMAT_REF.md`. Sample `.test` files exercising the full feature set are at `/app/test_files/` — these serve as ground truth for edge cases not covered in the reference.

The runner executes as: `python3 /app/sqllogictest_runner.py <test_file>` with exit code 0 on success/skip and non-zero on failure.

DuckDB is available via `import duckdb`.

```
```