`/app/` contains a custom SQLite migration tool (`migrate.py`) with five SQL migrations in `/app/migrations/`. The tool is broken — running `python3 /app/migrate.py migrate --db /app/test.db --migrations-dir /app/migrations` fails. A reference database at `/app/production.db` shows the correct end state after all migrations.

Fix the tool so that:

- All five migrations apply successfully against a fresh database
- Re-running is idempotent (already-applied migrations are skipped)
- The existing `verify` and `status` subcommands work correctly afterward

Then implement a `check` subcommand:

    python3 /app/migrate.py check --db <path> --migrations-dir <dir>

It must print exactly one JSON object to stdout:

```json
{
  "valid": <bool>,
  "total": <int>,
  "applied": <int>,
  "pending": <int>,
  "graph_valid": <bool>,
  "checksum_mismatches": [<string>, ...],
  "orphaned_records": [<string>, ...]
}
```

Field semantics:
- `valid`: `true` iff `graph_valid` is `true` and both lists are empty
- `total`: count of `.sql` files in the migrations directory
- `applied` / `pending`: counts by database tracking state
- `graph_valid`: `true` when the dependency graph is acyclic
- `checksum_mismatches`: migration IDs whose current file checksum differs from the stored checksum at apply time
- `orphaned_records`: migration IDs in the tracking table with no corresponding file on disk

Do not modify the `.sql` files in `/app/migrations/`.