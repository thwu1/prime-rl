A persistent key-value store is located at `/app/`. It supports `set`, `get`, `del`, and `scan` operations with crash-safe durability, backed by a single database file.

The store has a critical deficiency: **the database file grows without bound**. Deleting keys or overwriting existing values does not reduce — or even stabilize — the file size. Under sustained write workloads the file becomes impractically large.

Fix the store so that the file size remains bounded under realistic workloads. Your solution must satisfy all of the following:

- All existing operations produce correct results under arbitrary sequences of inserts, updates, and deletes, including across process restarts.
- Crash safety is preserved: an interrupted update must not leave the database in a corrupt state.
- After inserting 200 keys, deleting them all, and reinserting 200 new keys, the file size must be less than 1.5× the size after the initial insert.
- Five full cycles of inserting then deleting 100 keys must keep the file under 2 MB.
- Repeatedly updating the same 100 keys through 10 full value-replacement cycles must keep the file under 2× the size after initial insertion.

Build: `cd /app && go build -o /app/kvtool .`