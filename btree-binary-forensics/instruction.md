A persistent B+tree key-value store at `/app/database.db` has been left in an inconsistent state after a crash during a copy-on-write update cycle. The binary format is documented in `/app/format_spec.md`.

A Go-based B+tree invariant checker is provided as source at `/app/btree-tool/`. Compile and run it against the database to identify structural violations.

The database contains multiple distinct corruptions affecting the B+tree's internal node consistency, page allocation integrity, and free list bookkeeping. Diagnose every corruption, determine the correct state from the surrounding data, and produce a repaired database file.

Produce:

- `/app/report.json` with keys:
  - `violations`: array of `{"type": string, "page": int, "description": string}` for each corruption found
  - `page_map`: page number (string) to classification for pages `0` through `pages_used - 1`. Classifications: `meta`, `internal`, `leaf`, `free_list`, `free`, `orphaned_internal`, `orphaned_leaf`, `unused`
  - `tree_stats`: `{"depth": int, "internal_nodes": int, "leaf_nodes": int, "total_keys": int}` computed on the current (corrupted) tree

- `/app/database_repaired.db`: a corrected copy of the database where all structural violations have been resolved. The repaired database must pass the Go invariant checker with output `CONSISTENT`.