A trading firm's market data pipeline at `/app/` passes order updates between a network reader thread and a processing thread using a lock-free SPSC queue (`/app/include/spsc_queue.hpp`). The system is unreliable under concurrent operation:

- `make -C /app && /app/market_feed` intermittently reports data integrity errors. Throughput under contention is also lower than expected.
- A ThreadSanitizer-instrumented build is available via `make -C /app tsan` — running `/app/market_feed_tsan` may reveal additional information.

Diagnose and fix all correctness and performance defects in the codebase. The queue's public API (`push`, `consume_one`, constructor, destructor) and its lock-free property must be preserved.

Additionally, the team needs a batched variant for an aggregation pipeline. Create `/app/include/spsc_batch_queue.hpp` implementing `SPSCBatchQueue<T>` with:

- `explicit SPSCBatchQueue(std::size_t capacity)` — construct a queue holding exactly `capacity` items
- `bool push(const T& item)` — single-item push
- `bool push_batch(const T* items, std::size_t count)` — atomically publish `count` items; return false without side effects if insufficient space
- `bool consume_one(auto&& func)` — single-item consume
- `std::size_t consume_batch(auto&& func, std::size_t max_count)` — consume up to `max_count` items, calling `func` for each; return count consumed
- Destructor drains remaining items
- No copy/move

The batch queue must be production-grade: lock-free, data-race-free, and support types without a default constructor. Build with `make -C /app`.