The file `/app/sorted_set.py` provides a `SortedSet` class (conforming to `/app/interface.py`) that backs a production leaderboard service. The current implementation uses a naive sorted list and is functionally correct at small scale, but the verification suite enforces constraints it cannot satisfy:

- **Structural invariants**: the backing data structure must be a balanced tree with height bounded by O(log_8 N) and bucketed nodes holding multiple keys. A flat list or single-node structure will fail.
- **Asymptotic performance**: rank queries and insertions must run in O(log N) time. The verifier measures timing ratios between a 1K-element and 100K-element set; linear-time operations will exceed the allowed ratio.
- **C library integration**: a C helper library source is provided at `/app/node_ops.c` with header `/app/node_ops.h` and build rules in `/app/Makefile`. Compile it into `/app/libnode_ops.so` and integrate it via Python `ctypes` in your sorted set implementation for node-level operations.
- **Redis Lua validation**: a skeleton Redis Lua script at `/app/bulk_validate.lua` must be completed to perform deterministic bulk sorted set operations (insert 200 members, selectively remove and update, return card and probe ranks/scores). The test suite executes it via `redis-cli EVAL` and cross-validates against your implementation.
- **Redis-compatible semantics**: edge cases involving `+inf`/`-inf` scores, floating-point precision, lexicographic tiebreaking, and rank consistency after score updates are verified against a live Redis instance on `localhost:6379`.
- **Stress correctness**: 5000 random interleaved operations are cross-checked against a reference, and 10K-element full-range queries must match exactly.

A benchmark at `/app/benchmark.py` profiles the current implementation across dataset sizes, revealing where it breaks down.

Rewrite `/app/sorted_set.py`, compile the C library, and complete the Lua script so that all verification tests pass. Only modify files under `/app/`.