A trading system at `/app/` needs two concurrent data structures for its market data feed pipeline. A reference mutex-based queue at `/app/mutex_queue.hpp` defines the required API contract. The simulation at `/app/trading_sim.cpp` exercises both components together.

## 1. `/app/spsc_queue.hpp` — Lock-Free SPSC Queue

Implement a bounded Single-Producer Single-Consumer lock-free ring buffer queue matching the `SPSCQueue<T>` API in the mutex reference (`try_push`, `try_pop`, `capacity`, `size`).

- Lock-free using `std::atomic` — no mutexes
- A queue constructed with capacity N must hold exactly N elements (not N-1)
- Correct memory ordering for cross-thread data visibility on weakly-ordered architectures (ARM, RISC-V) — not all-relaxed, not all-seq_cst
- Producer and consumer hot variables must not share a cache line (prevent false sharing)

## 2. `/app/feed_merger.hpp` — K-Way Sorted Stream Merger

Implement `FeedMerger<T, KeyFn>` that merges K SPSC queues into a single sorted output stream keyed by `KeyFn`.

- Constructor: `FeedMerger(std::vector<SPSCQueue<T>*> sources, KeyFn key_fn)` where `key_fn(item)` returns the sort key
- `bool try_merge_one(T& out)` — pops the element with the smallest key across all non-empty sources into `out`. Returns false when all sources are exhausted.
- Per-element merge cost must be O(log K), not O(K)
- Stable: when keys are equal, output the element from the lower-indexed source first

Compile with `make` and run `./trading_sim` to validate both components together.