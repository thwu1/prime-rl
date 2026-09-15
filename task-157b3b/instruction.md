`/app/mpmc_queue.h` and `/app/backoff.h` contain empty stub declarations for a lock-free bounded multi-producer multi-consumer (MPMC) queue. `/app/stress_test.cpp` provides a multi-threaded correctness test harness (4 producers, 4 consumers, 50K items each) and `/app/Makefile` provides build rules.

Implement the complete lock-free MPMC queue in `/app/mpmc_queue.h`:

- Buffer size is always a power of two (minimum 2). The queue must not block — `enqueue` returns `false` when full, `dequeue` returns `false` when empty.
- Both operations must be safe for arbitrary numbers of concurrent producers and consumers without any mutex, spinlock, or blocking synchronization.
- The implementation must be correct on weakly-ordered architectures (ARM64), not just x86 TSO. Every atomic operation must use the minimum-sufficient C++ memory ordering.
- `try_enqueue_bulk` and `try_dequeue_bulk` must batch items more efficiently at the atomic coordination level than simply looping over single-item operations.
- Independently-accessed atomic variables must not share cache lines (prevent false sharing).
- Retry loops must integrate `adaptive_backoff` from `/app/backoff.h`.

Implement `/app/backoff.h` with an `adaptive_backoff` class providing `backoff()` and `reset()` methods. Under low contention it should be lightweight; under sustained contention it must escalate to yielding the thread.

Create `/app/ordering_analysis.json` documenting every atomic operation in your queue. Format: `{"operations": [...]}` with at least 6 entries covering both enqueue and dequeue paths. Each entry: `location` (method name), `variable` (atomic variable accessed), `operation` (load/store/compare_exchange), `ordering` (C++ memory order chosen), `justification` (why this ordering is necessary and sufficient), `weaker_ordering_bug` (a concrete interleaving on a weakly-ordered architecture showing what breaks with a weaker ordering).