Implement two components using the skeletons at `/app/mvcc_store.py` and `/app/mvcc_server.py`. All classes (`MVCCStore`, `Transaction`, `Watermark`, `CompactionFilter`, `ConflictError`) and method signatures are defined—fill in the implementations.

## Core Store (`/app/mvcc_store.py`)

`MVCCStore(db_path, serializable=True)` opens/creates a SQLite-backed versioned store. The database must contain a table called `versions` with columns `key TEXT, ts INTEGER, value TEXT` (composite PK `(key, ts)`), remain queryable via `sqlite3` CLI, and produce valid JSON with `sqlite3 -json` pipeable through `jq`.

`new_txn()` returns a `Transaction` with a snapshot-consistent view at creation time. Concurrent commits must not affect its reads.

**Transaction methods:** `get(key)` → value or `None`; `put(key, value)`; `delete(key)` (store as `NULL` value/tombstone); `scan(start, end)` → sorted `(key, value)` pairs in `[start, end)`; `commit()` → commit timestamp; `rollback()`. Uncommitted local writes are visible only within the owning transaction.

**Serializable mode** (`serializable=True`): `commit()` raises `ConflictError` when it would violate serializability—including write-skew (read-write conflicts via key hash comparison) and phantoms (a concurrent commit inserted/modified a key within a previously scanned range). Read-only transactions never conflict. When `serializable=False`, skip conflict validation entirely.

**Watermark:** reference-counted tracker via `add_reader(ts)` / `remove_reader(ts)`. `watermark()` returns the minimum active read timestamp, or `None` if empty. Multiple readers may share a timestamp.

**GC:** `gc()` removes versions at or below the watermark (or `latest_commit_ts` if no active readers), keeping only the newest version per key. If the newest version is a tombstone, remove all versions of that key. Keys matching any registered `CompactionFilter` are removed unconditionally. Returns total versions removed. Also cleans up stale serialization metadata.

`close()` flushes and closes the database.

## Socket Server (`/app/mvcc_server.py`)

CLI: `python3 /app/mvcc_server.py <socket_path> <db_path> [--serializable]`

Unix domain socket server accepting concurrent clients (one transaction per connection). Line-oriented protocol:

- `BEGIN` → `OK`
- `GET <key>` → `VALUE <val>` | `NONE`
- `PUT <key> <value>` → `OK`
- `DELETE <key>` → `OK`
- `SCAN <start> <end>` → `ITEM <key> <value>` per result, then `END`
- `COMMIT` → `COMMITTED <id>` | `CONFLICT <msg>`
- `ROLLBACK` → `OK`
- `GC` → `REMOVED <count>` (no transaction required)
- `QUIT` → close connection (implicit rollback)

Disconnection without commit implicitly rolls back. Must be drivable via `socat`.