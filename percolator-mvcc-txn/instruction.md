Implement a multi-versioned transactional key-value store at `/app/mvcc/`. Three skeleton files define the API contracts — fill in the implementations so that `/tests/test_state.py` passes.

**Components:**

- **`TimestampOracle`** (`/app/mvcc/oracle.py`): Monotonically increasing timestamp generator. Must produce globally unique timestamps across threads and independent OS processes.
- **`MemoryStorage`** (`/app/mvcc/storage.py`): Thread-safe versioned column store keyed by `(key, column, timestamp)`.
- **`Transaction`** (`/app/mvcc/transaction.py`): Snapshot-isolated transaction client supporting: consistent reads at a point-in-time snapshot, write-write conflict detection, atomic multi-key two-phase commit, recovery from partial commit failures (primary committed but secondaries dropped, and vice versa), and TTL-based cleanup of locks left by crashed transactions.

`redis-server` and Python 3 are available in the environment. Read the skeleton code and test suite to determine exact API semantics.