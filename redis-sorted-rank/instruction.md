A Redis-like key-value server is provided at `/app/`. It communicates via a custom binary protocol over TCP port 1234 and supports: `get`, `set`, `del`, `keys`, `zadd`, `zrem`, `zscore`, and `zquery`. Sorted sets maintain dual indexing — an AVL tree ordered by `(score, name)` for range operations and a chaining hashtable (with progressive rehashing) indexed by name for O(1) lookups.

Extend the server with these four commands:

**`zunionstore dest numkeys key [key ...] [weights w1 [w2 ...]] [aggregate sum|min|max]`** — Compute the union of `numkeys` sorted sets and store the result in `dest`, overwriting any existing key at `dest` regardless of its type. For members appearing in multiple source sets, multiply each score by its corresponding weight (default 1.0) then combine across sets using `sum` (default), `min`, or `max`. Members in only one set get their weighted score directly. Non-existent source keys are treated as empty sets. Return the cardinality of the resulting set as an integer. Return an error if any source key holds a non-sorted-set value. `numkeys` must be >= 1. If `dest` is also a source key, the original data must be fully read before being overwritten.

**`zinterstore dest numkeys key [key ...] [weights w1 [w2 ...]] [aggregate sum|min|max]`** — Like `zunionstore` but only members present in **all** source sets are included in the result. An empty or non-existent source set yields an empty result.

**`zremrangebyscore key min max`** — Remove all members from the sorted set at `key` whose score falls in the closed interval `[min, max]`. Both the tree index and hash index must remain consistent after bulk removal. Return the count of removed members as an integer. Return 0 for non-existent keys. Return an error if the key holds a non-sorted-set value.

**`zrangebyscore key min max [limit offset count]`** — Return members whose score is in `[min, max]` as an array of alternating `(name, score)` pairs (same output format as `zquery`). When `limit` is specified, skip `offset` matching members then return at most `count` members; a negative `count` means no upper bound on the number returned. Return an empty array for non-existent keys. Return an error if the key holds a non-sorted-set value.

Build with `make -C /app`.