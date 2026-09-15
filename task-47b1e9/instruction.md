A copy-on-write B+tree key-value store is implemented in Go at `/app/`. The store appends new pages for every update and never recycles freed pages — after repeated insert/delete cycles, the database file grows without bound.

The file `/app/freelist.go` defines a skeleton `FreeList` type with stub methods. The file `/app/kv.go` contains the working append-only KV store.

**Goal:** Eliminate the unbounded file growth by completing the page recycling implementation and integrating it into the KV store.

**Constraints:**

- Freed B+tree pages must be tracked and reused for future allocations.
- Pages freed during a single update must not be consumed until after that update is fully committed to disk.
- Recycling state must survive database close/reopen cycles.
- After inserting N keys, deleting all, and reinserting N new keys, the file size must be ≤ 2× the size after the initial insert batch.

**Verification deliverables:**

- `/app/io_protocol_report.txt` — Instrument the KV store's file operations (WriteAt and Sync calls) with a Go-level trace logger. Write a program that performs database inserts with the instrumentation enabled, then analyze the resulting I/O trace to demonstrate that the two-phase update protocol is correctly maintained: data page writes followed by fsync, then meta page write followed by fsync.

- `/app/meta_page_report.txt` — Use `xxd` to hex-dump the meta page (page 0) of a populated database file. Annotate each field with its name, byte range, and decoded little-endian value. Must cover at minimum: database signature, root pointer, and total page count.