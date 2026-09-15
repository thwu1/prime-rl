Implement a lock-free concurrent hash map in `/app/src/concurrent_hashmap.cpp` that satisfies the API defined in `/app/include/concurrent_hashmap.h`.

The hash map uses open addressing with linear probing over a flat array of `Cell` entries (each containing an atomic key and atomic value). Keys and values are `uint64_t`. Key `0` is reserved as the empty-slot marker (`NullKey`), value `0` indicates an empty or erased entry (`NullValue`), and value `1` (`Redirect`) signals that a cell has been migrated to a successor table during dynamic resizing.

## Requirements

- **Lock-free data path**: `insert`, `get`, and `erase` must be lock-free. Use compare-and-swap (CAS) to claim cells and update values. No mutexes on the data path.
- **Dynamic resizing via table migration**: When the table population (number of cells whose keys have been claimed) exceeds 75% of capacity, allocate a new table with double the capacity. Migrate every cell from the old table to the new one by CAS-ing each cell's value to `Redirect`, then inserting the captured value into the new table. Multiple threads must be able to cooperate on migration. Use `Table::migrateIndex` to partition migration work into chunks, and `Table::migrateComplete` to track chunk completion. Do not publish the new table as root until all chunks have finished.
- **QSBR integration**: Use the provided `QSBR` class (`/app/include/qsbr.h`) to safely defer destruction of old tables. After publishing a new root, enqueue the old table's `destroy()` via `m_qsbr.enqueue(...)`. The old table will be freed only after every registered thread has passed through a quiescent state.
- **Memory ordering**: Use appropriate `std::memory_order` qualifiers. The MurmurHash3 64-bit finalizer is provided in `/app/include/hash_util.h`.
- **Correctness under concurrency**: All public operations must be safe to call from any number of threads simultaneously. A correct implementation tolerates concurrent inserts, lookups, erases, and migrations without data loss, corruption, or undefined behavior.

The project skeleton (QSBR, hash utility, API header, and Makefile) is already in `/app/`.