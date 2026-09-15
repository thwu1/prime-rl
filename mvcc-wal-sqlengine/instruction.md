A minimal SQL database engine is provided at `/app/minidb/`. It supports CREATE TABLE, INSERT, SELECT (with WHERE), UPDATE, and DELETE on in-memory tables. It currently has no transaction support, no concurrency control, and no durability.

Extend this engine so that it satisfies all of the following:

**Concurrent multi-session transactions with isolation.** Multiple sessions must be able to operate on the database concurrently. Uncommitted changes from one session must never be visible to another session. A session must always see its own pending writes. If two active transactions both attempt to modify the same row, the engine must raise a `TransactionConflict` exception. Once a transaction begins, its reads must not be affected by commits from other sessions that occur after that point. `BEGIN`, `COMMIT`, and `ROLLBACK` must be recognized as SQL statements. Statements executed outside an explicit transaction must auto-commit individually.

**Durable persistence using the provided protobuf schema.** A `.proto` schema defining `WalRecord` and `CheckpointData` message types is provided at `/app/minidb/wal.proto`. When a `Database` is constructed with a `data_dir` argument, committed data must survive process restarts. Uncommitted transactions must be discarded on restart. Persistence files must be named `wal.bin` and `checkpoint.bin` within `data_dir`. The persistence format must be binary protobuf — not JSON or text. Calling `db.checkpoint()` must write a compact snapshot and allow prior log entries to be reclaimed. Recovery after restart must incorporate any checkpoint and subsequent log entries.

**Build pipeline.** A `Makefile` at `/app/Makefile` must provide a `proto` target that generates Python code from the `.proto` schema and a `clean` target that removes generated artifacts.

## API Contract

```
Database(data_dir=None)
db.session() -> Session
db.execute(sql) -> ResultSet   # auto-commit convenience
db.checkpoint()
db.close()

session.execute(sql) -> ResultSet

ResultSet.columns  # list[str]
ResultSet.rows     # list[list]
ResultSet.message  # str

TransactionConflict  # exception class, importable from minidb
```