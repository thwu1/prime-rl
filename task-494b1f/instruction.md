Build a text buffer system in `/app/`.

## Text Buffer Library

Implement the `PieceTable` class in `/app/piece_table.py` (stub with method signatures provided).

- `insert`, `delete`, and `char_at` must run in O(log n) amortized time where n is the number of internal segments. O(n) per-operation implementations will fail performance tests.
- Snapshots via `snapshot()` must remain valid after arbitrary subsequent edits.
- Undo history is a tree, not a stack: after undo + new edit, the old redo path is preserved as a branch navigable via `redo(branch_index)`.
- `diff_snapshots(a, b)` returns a minimal line-level diff as `(op, line)` tuples (`'+'`, `'-'`, `' '`).
- All introspection methods (`_tree_height`, `_piece_count`, `_is_balanced`, `_get_buffers`) must work correctly.

## Makefile-Driven Journal Replay Pipeline

A binary edit journal is at `/app/journal.bin` (format documented in `/app/journal_format.txt`). Build a pipeline orchestrated by a Makefile at `/app/Makefile` with these targets and dependency ordering:

- **`validate`** — use `xxd` to extract the 8-byte binary header of the journal, write the hex dump to `/app/output/header_hex.txt`, verify magic bytes ("PTEDIT" = `505445444954`) and version (`01`), and create `/app/output/journal_valid.stamp` on success.
- **`replay`** (depends on `validate`) — replay the journal through PieceTable, writing `/app/output/snapshots/snapshot_N.txt` per checkpoint.
- **`diffs`** (depends on `replay`) — generate unified diffs between consecutive snapshots as `/app/output/diffs/diff_A_B.patch` (must apply cleanly with `patch`).
- **`database`** (depends on `diffs`) — create SQLite DB at `/app/output/versions.db`:
  - `snapshots(id INTEGER PRIMARY KEY, content TEXT, line_count INTEGER, char_count INTEGER)`
  - `diffs(id INTEGER PRIMARY KEY AUTOINCREMENT, from_snapshot INTEGER, to_snapshot INTEGER, additions INTEGER, deletions INTEGER)`
- **`report`** (depends on `database`) — use the **`sqlite3` command-line tool** (not Python) to query `versions.db` and produce `/app/output/report.txt` containing: a header line `=== Version Report ===`, a column-formatted snapshot table (id, line_count, char_count), a line `--- Diff Summary ---`, and a total additions/deletions summary.
- **`all`** — full pipeline in correct dependency order. **`clean`** — remove `/app/output/`.

Entry point `/app/replay_journal.sh` must invoke `make -C /app all`.