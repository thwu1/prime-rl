A C++17 concurrent hash map library is provided at `/app/concurrent_map.h`. It implements a lock-free hash map using open addressing with linear probing, CAS-based insertion, and a QSBR (Quiescent-State-Based Reclamation) system for safe memory management.

The map's core operations (`get`, `assign`, `erase`) work correctly on a single fixed-size table. However, when the table reaches 75% load, `doResize()` is called — and its current implementation simply allocates a new empty table, discarding all existing entries. Every resize silently loses all data.

Design and implement a correct concurrent table migration protocol. The resize operation must atomically transfer all entries from the old table to a new, larger table while concurrent reads, writes, and erases continue without blocking or losing data. After migration completes, all previously stored entries must be accessible through the new table, and the old table must be safely deallocated.

You will need to modify `doResize()` and also `get()`, `assign()`, and `erase()` — and possibly `Table::insertOrFind()` — to correctly handle the intermediate states that exist during migration. The header defines a `REDIRECT_VAL` sentinel and a `frozen` flag on each `Table`; these are unused scaffolding that you may find useful, but any correct approach is acceptable.

Modify only `/app/concurrent_map.h`. Do not change the public API (`ConcurrentMap` class name, method signatures, or the `Context` type alias).