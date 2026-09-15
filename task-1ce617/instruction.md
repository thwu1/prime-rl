A Redis-like key-value server is provided at `/app/src/`. The server has a working TCP event loop, binary protocol parser, GET/SET/DEL/KEYS commands, and a hashtable with progressive rehashing. However, three source files (`avl.cpp`, `zset.cpp`, `heap.cpp`) contain only `abort()` stubs, making the sorted set commands (ZADD, ZREM, ZSCORE, ZQUERY) and TTL commands (PEXPIRE, PTTL) crash the server when invoked.

Your task is to provide working implementations for the three stubbed files in `/app/src/` so that all server commands function correctly. The function signatures and data structure definitions are declared in the corresponding header files (`avl.h`, `zset.h`, `heap.h`). The rest of the server code (`server.cpp`, `hashtable.cpp`, `common.h`, etc.) is complete and must not be modified — your implementations must conform to the existing APIs and integrate with how the server already calls these functions.

The server must correctly support:
- **ZADD** `key score name` — add or update a member's score in a sorted set
- **ZREM** `key name` — remove a member from a sorted set
- **ZSCORE** `key name` — retrieve a member's score
- **ZQUERY** `key score name offset limit` — range query returning members in `(score, name)` order, starting from the first entry >= `(score, name)`, skipping `offset` entries, returning up to `limit` entries (each entry is a name+score pair)
- **PEXPIRE** `key ttl_ms` — set a millisecond TTL on any key
- **PTTL** `key` — query remaining TTL (-1 if none, -2 if key doesn't exist)

Keys with expired TTLs must be automatically removed by the server's timer processing.

Build with `make -C /app/src`. The server binary is `/app/src/server` and listens on TCP port 1234.