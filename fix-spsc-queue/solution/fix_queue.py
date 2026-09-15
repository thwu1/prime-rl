#!/usr/bin/env python3
"""
Fix all bugs in the SPSC queue implementation at /app/include/spsc_queue.hpp.

Bug 1 (Capacity sentinel): The ring buffer needs capacity+1 slots to hold
capacity items, because one slot is always unused to distinguish full from empty.
The constructor stores capacity_ = capacity instead of capacity + 1.

Bug 2 (Memory ordering - tail path): tail_.store in push() uses relaxed ordering,
but must use release so that the preceding construct_at is visible to the consumer.
tail_.load in consume_one() uses relaxed but must use acquire to synchronize with
the producer's release store.

Bug 3 (Memory ordering - head path): head_.store in consume_one() uses relaxed
but must use release so that the preceding destroy_at is complete before the
producer reuses the slot. head_.load in push() uses relaxed but must use acquire
to synchronize with the consumer's release store.

Bug 4 (False sharing): head_ and tail_ are adjacent class members on the same
cache line. Since the producer writes tail_ and reads head_, while the consumer
writes head_ and reads tail_, every atomic update invalidates the other core's
cache line. Fix: alignas(64) on each atomic to place them on separate cache lines.
"""

QUEUE_FILE = "/app/include/spsc_queue.hpp"

with open(QUEUE_FILE) as f:
    content = f.read()

# ---- Fix 1: Capacity sentinel slot ----
content = content.replace(
    "        : capacity_{capacity}\n",
    "        : capacity_{capacity + 1}\n",
)

# ---- Fix 2: Memory ordering on tail (producer->consumer sync) ----

# tail_.store in push: relaxed -> release
content = content.replace(
    "        tail_.store(next_tail, std::memory_order_relaxed);",
    "        tail_.store(next_tail, std::memory_order_release);",
)

# tail_.load in consume_one: relaxed -> acquire
content = content.replace(
    "        if (curr_head == tail_.load(std::memory_order_relaxed))",
    "        if (curr_head == tail_.load(std::memory_order_acquire))",
)

# ---- Fix 3: Memory ordering on head (consumer->producer sync) ----

# head_.store in consume_one: relaxed -> release
content = content.replace(
    "        head_.store((curr_head + 1) % capacity_, std::memory_order_relaxed);",
    "        head_.store((curr_head + 1) % capacity_, std::memory_order_release);",
)

# head_.load in push: relaxed -> acquire
content = content.replace(
    "        if (next_tail == head_.load(std::memory_order_relaxed))",
    "        if (next_tail == head_.load(std::memory_order_acquire))",
)

# ---- Fix 4: False sharing ----

# Add cache line size constant before the class definition
cache_line_block = """\

#ifdef __cpp_lib_hardware_interference_size
inline constexpr std::size_t kCacheLineSize = std::hardware_destructive_interference_size;
#else
inline constexpr std::size_t kCacheLineSize = 64;
#endif

// Lock-free Single Producer"""

content = content.replace(
    "\n// Lock-free Single Producer",
    cache_line_block,
)

# Add alignas to head_ and tail_ to place them on separate cache lines
content = content.replace(
    "    std::atomic<std::size_t> head_{0};",
    "    alignas(kCacheLineSize) std::atomic<std::size_t> head_{0};",
)
content = content.replace(
    "    std::atomic<std::size_t> tail_{0};",
    "    alignas(kCacheLineSize) std::atomic<std::size_t> tail_{0};",
)

with open(QUEUE_FILE, "w") as f:
    f.write(content)

print("All bugs fixed in spsc_queue.hpp:")
print("  1. Capacity sentinel: capacity_ = capacity + 1")
print("  2. Memory ordering: acquire/release on cross-thread atomics")
print("  3. False sharing: alignas(kCacheLineSize) on head_ and tail_")
