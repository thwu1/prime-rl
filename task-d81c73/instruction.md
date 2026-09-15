A trading order pipeline at `/app/` uses a lock-free SPSC (single-producer, single-consumer) queue (`/app/spsc_queue.h`) and a latency sampler (`/app/latency_sampler.h`) for inter-thread communication and performance monitoring. The system has multiple issues:

- The pipeline produces data corruption under concurrent use with certain queue capacities. The smoke test (`make -C /app && /app/pipeline`) reports sequence errors and attributes them to the latency sampling infrastructure — but the diagnostic messages may be misleading.
- The latency sampler has concurrency bugs causing data races under concurrent writer/reader access.
- The queue lacks batch enqueue/dequeue operations needed for market data burst handling — see the `push_batch`/`pop_batch` stubs in the header.

Debug and fix all correctness and concurrency issues across both components, then design and implement the batch operations. The fixed system must:

1. Handle arbitrary queue capacities (not just powers of 2) correctly through unbounded wraparound cycles
2. Be free of data races under the C++ memory model (must pass ThreadSanitizer)
3. Eliminate cache-line false sharing between producer and consumer hot paths
4. Provide working `push_batch(items, count)` and `pop_batch(out, count)` that each perform a single snapshot of available space/items, transfer up to that many elements, and return the count actually transferred
5. Produce correct latency readings from the sampler under concurrent writer/reader access

Preserve the existing public API signatures and the header-only template structure of both components.