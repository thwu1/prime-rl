Implement `/app/hashtable.c` conforming to the API declared in `/app/hashtable.h`. Running `make -C /app` must produce `/app/libblockht.so`.

The hash table stores arbitrary-length byte-sequence keys and values. It must satisfy the following observable properties:

- `bht_verify_alignment()` returns 1: all internal block arrays are aligned to 64-byte cache-line boundaries.
- `bht_avg_probe_distance()` returns ≤ 2.0 when the table is at or below 70% load factor.
- Resizing is incremental — amortized across mutating operations rather than performed in a single blocking pass. `bht_is_resizing()` returns 1 while entry migration is in progress, 0 otherwise.
- All entries remain accessible via `bht_lookup` during and after a resize operation.
- Deletion of entries works correctly at all times, including mid-resize, and must not permanently degrade probe-distance characteristics.
- Per-entry memory overhead (`bht_memory_usage()` minus total raw key+value bytes, divided by entry count) must be ≤ 32 bytes when measured at ≥ 65% load factor and not mid-resize.

Refer to `/app/hashtable.h` for the complete function signatures, parameter semantics, and return conventions.