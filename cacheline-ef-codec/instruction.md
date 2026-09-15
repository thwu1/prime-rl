A *minimal perfect hash function* (MPHF) maps a static set of *n* distinct keys bijectively to {0, 1, ..., n-1}. No collisions, no wasted indices.

`/app/ptrhash.h` declares an opaque `PtrHash` type and three functions. Implement them in `/app/ptrhash.c`:

- `ptrhash_build(keys, n)` — construct an MPHF over `n` distinct `uint64_t` keys. Return a heap-allocated `PtrHash *` on success, `NULL` on failure.
- `ptrhash_query(ph, key)` — return the unique index in {0, ..., n-1} for a key from the build set.
- `ptrhash_free(ph)` — free all resources. `NULL` input must be safe.

The header also provides hash and integer-reduction utility functions.

**Requirements:**

- For every input key, `ptrhash_query` returns a distinct value in [0, n) — the mapping must be a bijection
- Construction must reliably succeed for inputs from 0 to 100,000 keys across varied random distributions
- Queries must be deterministic

**Compilation:**
```
gcc -O2 -std=c11 -Wall -Wextra -o ptrhash_test /app/ptrhash.c /tests/test_main.c -I/app -lm
```