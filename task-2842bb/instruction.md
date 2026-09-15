The header file `/app/hashtable.h` defines the complete API for a block-based hash table that stores variable-length key-value records. Implement all functions in `/app/hashtable.c` and produce a compiled shared library at `/app/libhashtable.so`.

## Behavioral Requirements

**Storage model**: Variable-length records (key + value) are packed into fixed-size memory blocks. Per-record `malloc` is prohibited — all record data must reside in block-allocated memory. When no existing block has room, allocate a new one. Records larger than the configured block size must still be stored (the allocated block must be large enough). `bht_block_count()` and `bht_block_size()` expose pool state.

**Probe behavior**: The maximum probe sequence length (PSL) across all occupied slots must remain bounded at O(log n) for n stored entries, maintained through both insertions and deletions. The implementation must achieve this bound — a naive open-addressing scheme will not suffice.

**Deletion semantics**: Deletion must not use tombstones or sentinel markers. Removing an entry must preserve correct and efficient lookup for all remaining entries, including those whose probe sequences passed through the deleted slot.

**Resize behavior**: When load factor exceeds 0.7, the slot array capacity doubles. Migration of existing entries to the new array must be amortized across subsequent API calls — not completed in a single blocking pass. `bht_uses_incremental_resize()` returns 1 while migration is active. All operations must handle entries in both old and new arrays correctly during the migration window.

**Key/value sizes**: Keys 1–4000 bytes, values 0–4000 bytes.

## Library Constraints

The compiled shared library `/app/libhashtable.so` must export **only** the public `bht_*` functions declared in the header. All internal functions, static data, and helper routines must be hidden from the dynamic symbol table.

The implementation must be free of memory leaks. Every `bht_create`/`bht_destroy` cycle must release all allocated resources with zero leaks, including when a resize is in progress at the time of destruction.