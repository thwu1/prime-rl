A Redis-like key-value server at `/app/` implements GET, SET, DEL, KEYS, ZADD, ZREM, ZSCORE, ZQUERY, PEXPIRE, and PTTL over a custom binary protocol (TCP port 1234). Its hashtable uses two-table progressive rehashing — during resizing, keys migrate incrementally from the older table to the newer one across operations.

Implement a `SCAN` command for cursor-based iteration over all database keys.

## Command

`scan <cursor> [count <n>]`
- `cursor`: uint64, pass `0` to start a new iteration
- `count`: optional batch-size hint (default 10)

Response: array of exactly 2 elements — next cursor (int64, `0` = done) and an array of key strings.

## Constraints

- A full iteration (repeated SCAN calls until cursor returns `0`) must return every key that was present throughout the entire iteration. Keys added/removed mid-scan may or may not appear.
- The cursor is a stateless opaque integer — no per-scan server state between calls.
- The cursor algorithm must handle progressive rehashing correctly: when the table resizes between SCAN calls (the `newer`/`older` HTab fields in HMap change), keys must not be systematically missed. Study how the hashtable's `newer` and `older` tables interact during rehashing before choosing a cursor encoding.
- Empty database: return cursor `0` and empty array immediately.
- COUNT is advisory — actual per-call batch size may vary.

Wire up the command in `do_request()` and serialize responses with `out_arr`/`out_int`/`out_str`. Rebuild: `cd /app && make clean && make`