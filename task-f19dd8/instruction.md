A transactional database engine simulator crashed mid-operation. The crash state is captured across multiple data sources: a SQLite database containing structured WAL records and checkpoint snapshots, a binary page state file recording which data pages were flushed to disk, and an optional binary WAL suffix containing late-arriving log records that were appended to the write-ahead log but not yet reflected in the SQLite catalog.

Build an executable tool at `/app/recover` that analyzes a crash scenario and determines what recovery actions are needed:

```
/app/recover <crash.db> <output.json>
```

The tool must discover and parse companion binary files alongside the crash database:
- `<crash.db>.pgstate` — flushed page state in the PGST binary format
- `<crash.db>.walsuffix` — additional WAL records in the WAL1 binary format (may not exist if all records are in the SQLite database)

Both binary formats use big-endian byte ordering and a fixed-size record layout documented in `/app/BINARY_FORMAT.md`. Use `xxd` or `od` to inspect the binary files interactively.

The tool must produce a JSON report covering:
- The state of in-flight transactions at crash time, incorporating any checkpoint data
- Which logged page modifications must be replayed to restore durability
- Which incomplete transactions must be reversed, including the compensation records generated during reversal and the order in which transactions complete reversal

The crash database schema is at `/app/schema.sql`. Output format and field semantics are in `/app/FORMAT.md`. Binary format specifications are in `/app/BINARY_FORMAT.md`. A worked example is in `/app/examples/` — explore the example database, binary files, and expected output to understand the precise recovery semantics.