`/app/mvcc.py` contains stub classes for a multi-version concurrency control transaction engine. Implement all methods so that `cd /app && make test` passes. Do not rename any exported classes or constants.

## Storage Requirement

A Redis server is installed at `/usr/bin/redis-server` but is **not running**. You must start and configure it appropriately. All versioned data managed by `KvTable` must be persisted in Redis on `localhost:6379` — not in in-memory Python data structures. Use `redis-cli` to inspect your data layout during development. The `make check-redis` target can verify connectivity.

## Components

- **TimestampOracle**: Thread-safe, strictly-increasing timestamp generator. Every call to `get_timestamp()` must return a globally unique value, even under concurrent access.
- **KvTable**: Versioned key-value store with three column families (`Column.WRITE`, `Column.DATA`, `Column.LOCK`). Each entry is keyed by `(key, timestamp)`. `read()` returns the entry with the largest timestamp within an optional `[ts_start, ts_end]` range. All column family data must reside in Redis.
- **MemoryStorage**: Provides transactional operations over `KvTable` with appropriate conflict detection and concurrency control.
- **Client**: Buffers writes locally. `commit()` writes them atomically through `MemoryStorage`.

## Isolation Guarantees

The engine must provide **snapshot isolation**: each transaction reads from a consistent point-in-time view. Concurrent writes to non-overlapping key sets must all succeed. Concurrent writes to the same key must result in at most one transaction succeeding. Abandoned operations (identified by `LOCK_TTL_SECS` expiry) must be cleaned up so they do not block future transactions.

Tests include concurrency anomaly checks, recovery scenarios, concurrent stress tests, property-based invariant tests, and Redis integration verification.