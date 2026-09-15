A Redis-like key-value server at `/app/` supports GET, SET, DEL, KEYS, ZADD, ZREM, ZSCORE, and ZQUERY via a custom binary protocol on TCP port 1234. The server uses a poll()-based event loop with non-blocking I/O, intrusive data structures (chaining hashtable with progressive rehashing, AVL tree with subtree counts, sorted sets with dual indexing), and a thread pool for async deletion. Build with `make` in `/app/`.

Several features are incomplete:

1. `avl_offset` in `/app/avl.cpp` is stubbed (returns NULL), breaking ZQUERY's offset/pagination. It must navigate to the node at rank offset from a given node in O(log N) time using subtree counts (`cnt` field) and parent pointers.

2. The min-heap in `/app/heap.cpp` is unimplemented. `HeapItem` has a `val` (priority value) and a `ref` (pointer to a `size_t` tracking the item's current position in the heap array). When items are swapped during sift-up/sift-down, `*ref` must be updated to the new position.

3. TTL key expiration is missing. The server needs: a `heap_idx` field on each Entry (initialized to `(size_t)-1`), a `std::vector<HeapItem>` in global state, `PEXPIRE key ttl_ms` (set millisecond TTL, returns 1 if key exists else 0), `PTTL key` (returns remaining ms, -1 if no TTL, -2 if key missing), and event loop timer processing that uses the heap to find and delete expired keys each iteration.

4. `ZRANGEBYSCORE key min max offset limit` is missing. It returns (name, score) pairs where `min <= score <= max`, applying `offset` via `znode_offset` from the first matching position, with `limit` counting individual items (each name and score counts as 1, consistent with ZQUERY).

The binary protocol uses 4-byte little-endian length-prefixed messages. Requests encode an array of strings: `nstr:u32 [len:u32 str:bytes]...`. Responses are tagged values: NIL(0), ERR(1, code:u32, len:u32, msg), STR(2, len:u32, data), INT(3, val:i64), DBL(4, val:f64), ARR(5, n:u32, items...).