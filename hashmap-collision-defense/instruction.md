`/app/` contains a C implementation of a key-value store backed by a hash table with linear probing. The hash function in `/app/src/hashtable.c` uses a fixed-constant multiply-shift scheme, making it algebraically vulnerable to hash-flooding.

**Part 1 — Attack:** Analyze the hash function and exploit its algebraic structure to generate a collision set. Create `/app/adversarial_input.txt` containing at least 10,000 unique `uint64_t` values (one per line, decimal), of which at least 95% must hash to the same bucket under the current hash function.

**Part 2 — Defense:** Modify `/app/src/hashtable.h` and `/app/src/hashtable.c` to resist hash-flooding. Constraints:
- Must compile with `make -C /app`
- Function signatures for `ht_init`, `ht_insert`, `ht_lookup`, `ht_delete` must not change
- `TABLE_BITS` (16), `TABLE_SIZE` (65536), `TABLE_MASK` (65535), and the `Entry` struct must remain unchanged; you may add fields to `HashTable` but not remove existing ones
- All operations (insert, lookup, delete, update-on-duplicate, load-factor rejection at 3/4) must remain correct
- When the adversarial keys are inserted, the maximum contiguous run of occupied entries in the backing array must be under 500
- All hash-table logic must remain in `hashtable.h` and `hashtable.c` (no additional source files)